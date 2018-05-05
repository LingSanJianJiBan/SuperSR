
from keras.models import Model
from keras.layers import Concatenate, Add, Average, Input, Dense, Flatten, BatchNormalization, Activation, LeakyReLU
from keras.layers.core import Lambda
from keras.layers.convolutional import Convolution2D, MaxPooling2D, UpSampling2D, Convolution2DTranspose
from keras.utils.np_utils import to_categorical
from keras.utils.io_utils import HDF5Matrix
import keras.callbacks as callbacks
import keras.optimizers as optimizers
from keras import backend as K
from advanced import  SubPixelUpscaling,  TensorBoardBatch
from image_utils import Dataset, downsample, merge_to_whole
from utils import psnr_k, psnr_np
import numpy as np
import os
import warnings
import scipy.misc
import h5py
import tensorflow as tf

class BaseSRModel(object):
    def __init__(self, model_name, input_size, channel):
        """
        Input:
            model_name, str, name of this model
            input_size, tuple, size of input. 
            channel, int, num of channel of input. 
        """
        self.model_name = model_name
        self.weight_path=None
        self.input_size=input_size
        self.channel=channel
        self.model=self.create_model(load_weights=False)

    def create_model(self, load_weights=False) -> Model:

        init = Input(shape=self.input_size)
        return init

    def fit(self, 
            train_dst=Dataset('./test_image/'), 
            val_dst=Dataset('./test_image/'),
            big_batch_size=1000, 
            batch_size=16, 
            learning_rate=1e-4, 
            loss='mse', 
            shuffle=True,
            visual_graph=True, 
            visual_grads=True, 
            visual_weight_image=True, 
            multiprocess=False,
            nb_epochs=100, 
            save_history=True, 
            log_dir='./logs') -> Model:
        
        assert train_dst._is_saved(), 'Please save the data and label in train_dst first!'
        assert val_dst._is_saved(), 'Please save the data and label in val_dst first!'
        train_count = train_dst.get_num_data()
        val_count = val_dst.get_num_data()

        if self.model == None: self.create_model()

        adam = optimizers.Adam(lr=learning_rate)
        self.model.compile(optimizer=adam, loss=loss, metrics=[psnr_k])

        callback_list = []
        callback_list.append(callbacks.ModelCheckpoint(self.weight_path, monitor='val_loss',
                                                        save_best_only=True, mode='min', 
                                                        save_weights_only=True, verbose=2))
        if save_history:
            callback_list.append(TensorBoardBatch(log_dir=log_dir, batch_size=batch_size, histogram_freq=1,
                                                    write_grads=visual_grads, write_graph=visual_graph, write_images=visual_weight_image))

        print('Training model : %s'%(self.model_name))

        self.model.fit_generator(train_dst.image_flow(big_batch_size=big_batch_size, batch_size=batch_size, shuffle=shuffle),
                                steps_per_epoch=train_count // batch_size + 1, epochs=nb_epochs, callbacks=callback_list, 
                                validation_data=val_dst.image_flow(big_batch_size=10*batch_size, batch_size=batch_size, shuffle=shuffle),
                                validation_steps=val_count // batch_size + 1, use_multiprocessing=multiprocess, workers=4)
        return self.model                     


    def gen_sr_img(self, test_dst=Dataset('./test_image/'), image_name='Spidy.jpg', save = False, verbose=0):
        """
        Generate the high-resolution picture with trained model. 
        Input:
            test_dst: Dataset, Instance of Dataset. 
            image_name : str, name of image.
            save : Bool, whether to save the sr-image to local or not.  
            verbose, int.
        Return:
            orig_img, bicubic_img, sr_img and psnr of the hr_img and sr_img. 
        """
        stride = test_dst.stride
        scale = test_dst.scale
        lr_size = test_dst.lr_size
        assert test_dst.slice_mode=='normal', 'Cannot be merged if blocks are not completed. '

        data, label, size_merge = test_dst._data_label_(image_name)
        output = self.model.predict(data, verbose=verbose)
        # merge all subimages. 
        hr_img = merge_to_whole(label, size_merge, stride = stride)
        lr_img = downsample(hr_img, scale=scale, lr_size=lr_size)
        sr_img = merge_to_whole(output, size_merge, stride = stride)
        if verbose == 1:
            print('PSNR is %f'%(psnr_np(sr_img, hr_img)))
        if save:
            scipy.misc.imsave(sr_img, './example/%s_SR.png'%(image_name))
        return hr_img, lr_img, sr_img, psnr_np(sr_img, hr_img)

    def evaluate(self, test_dst=Dataset('./test_image/'), verbose = 0) -> Model:
        """
        evaluate the psnr of whole images which have been merged. 
        Input:
            test_dst, Dataset. A instance of Dataset. 
            verbose, int. 
        Return:
            average psnr of images in test_path. 
        """
        PSNR = []
        test_path = test_dst.image_dir
        for _, _, files in os.walk(test_path):
            for image_name in files:
                # Read in image 
                _, _, _, psnr =  self.gen_sr_img(test_dst, image_name)
                PSNR.append(psnr)
        ave_psnr = np.sum(PSNR)/float(len(PSNR))
        print('average psnr of test images(whole) in %s is %f. \n'%(test_path, ave_psnr))
        return ave_psnr


class SRCNN(BaseSRModel):
    """
    pass
    """
    def __init__(self, model_type, input_size, channel):
        """
        Input:
            model_type, str, name of this SRCNN-net. 
            input_size, tuple, size of input layer. 
            channel, int, num of channels of input data. 
        """
        self.f1 = 9
        self.f2 = 1
        self.f3 = 5

        self.n1 = 64
        self.n2 = 32

        self.weight_path = "weights/SRCNN Weights %s.h5" % (model_type)
        super(SRCNN, self).__init__("SRCNN"+model_type, input_size, channel)        
    
    def create_model(self, load_weights=False):

        init = super(SRCNN, self).create_model()

        x = Convolution2D(self.n1, (self.f1, self.f1), activation='relu', padding='same', name='level1')(init)
        x = Convolution2D(self.n2, (self.f2, self.f2), activation='relu', padding='same', name='level2')(x)

        out = Convolution2D(self.channel, (self.f3, self.f3), padding='same', name='output')(x)

        model = Model(init, out)

        if load_weights: 
            model.load_weights(self.weight_path)
            print("loaded model%s"%(self.model_name))

        self.model = model
        return model
    


        
class ResNetSR(BaseSRModel):
    """
    Under test. A little different from original paper. 
    """

    def __init__(self, model_type, input_size, channel, scale):

        self.n = 64
        self.mode = 2
        self.f = 3  
        self.scale = scale

        self.weight_path = "weights/ResNetSR Weights %s.h5" % (model_type)
        super(ResNetSR, self).__init__("ResNetSR"+model_type, input_size, channel)

    def create_model(self, load_weights=False, nb_residual = 5):

        init =  super(ResNetSR, self).create_model()

        x0 = Convolution2D(self.n, (self.f, self.f), activation='relu', padding='same', name='sr_res_conv1')(init)

        x = self._residual_block(x0, 1)

        nb_residual = nb_residual-1
        for i in range(nb_residual):
            x = self._residual_block(x, i + 2)

        x = Add()([x, x0])

        x = self._upscale_block(x, 1)

        x = Convolution2D(self.channel, (self.f, self.f), activation="linear", padding='same', name='sr_res_conv_final')(x)

        model = Model(init, x)
        if load_weights: model.load_weights(self.weight_path, by_name=True)

        self.model = model
        return model
    
    

    def _residual_block(self, ip, id):
        mode = False if self.mode == 2 else None
        channel_axis = 1 if K.image_data_format() == 'channels_first' else -1
        init = ip

        x = Convolution2D(self.n, (self.f, self.f), activation='linear', padding='same',
                          name='sr_res_conv_' + str(id) + '_1')(ip)
        x = BatchNormalization(axis=channel_axis, name="sr_res_batchnorm_" + str(id) + "_1")(x, training=mode)
        x = Activation('relu', name="sr_res_activation_" + str(id) + "_1")(x)

        x = Convolution2D(self.n, (self.f, self.f), activation='linear', padding='same',
                          name='sr_res_conv_' + str(id) + '_2')(x)
        x = BatchNormalization(axis=channel_axis, name="sr_res_batchnorm_" + str(id) + "_2")(x, training=mode)

        m = Add(name="sr_res_merge_" + str(id))([x, init])

        return m

    def _upscale_block(self, ip, id):
        init = ip

        channel_dim = 1 if K.image_data_format() == 'channels_first' else -1
        channels = init._keras_shape[channel_dim]

        #x = Convolution2D(256, (self.f, self.f), activation="relu", padding='same', name='sr_res_upconv1_%d' % id)(init)
        #x = SubPixelUpscaling(r=2, channels=self.n, name='sr_res_upscale1_%d' % id)(x)
        x = UpSampling2D()(init)
        x = Convolution2D(self.n, (self.f, self.f), activation="relu", padding='same', name='sr_res_filter1_%d' % id)(x)

        # x = Convolution2DTranspose(channels, (4, 4), strides=(2, 2), padding='same', activation='relu',
        #                            name='upsampling_deconv_%d' % id)(init)

        return x

    def fit(self, batch_size=128, nb_epochs=100, save_history=True, history_fn="ResNetSR History.txt"):
        super(ResNetSR, self).fit(batch_size, nb_epochs, save_history, history_fn)

class EDSR(BaseSRModel):

	def __init__(self, model_type, input_size, channel, scale):

		self.n = 64 # size of feature. also known as number of filters. 
		self.f = 3 # shape of filter. 
		self.scale_res = 1 # used in each residual net
		self.scale = scale # by diff scales comes to diff model structure in upsampling layers. 
		self.weight_path = "weights/EDSR Weights %s.h5" % (model_type)
		super(EDSR, self).__init__("EDSR"+model_type, input_size, channel)

	def create_model(self, load_weights = False, nb_residual = 10):

		init = super(EDSR, self).create_model()

		x0 = Convolution2D(self.n, (self.f, self.f), activation='relu', padding='same', name='sr_conv1')(init)

		x = self._residual_block(x0, 1, scale=self.scale_res)

		nb_residual = nb_residual - 1
		for i in range(nb_residual):
			x = self._residual_block(x, i + 2, scale=self.scale_res)

		x = Convolution2D(self.n, (self.f, self.f), activation='relu', padding='same', name='sr_conv2')(x)
		x = Add()([x, x0])

		x = self._upsample(x)

		out = Convolution2D(self.channel, (self.f, self.f), activation="relu", padding='same', name='sr_conv_final')(x)

		model = Model(init, out)
		adam = optimizers.Adam(lr=1e-4)
		model.compile(optimizer=adam, loss='mae', metrics=[psnr_k])

		if load_weights: 
			model.load_weights(self.weight_path, by_name=True)
			print("loading model", self.weight_path)

		self.model = model
		return model


    # def _residual_block(self, ip, id, scale):

    #     init = ip

    #     x = Convolution2D(self.n, (self.f, self.f), activation='linear', padding='same',
    #                         name='sr_res_conv_' + str(id) + '_1')(ip)
    #     x = Activation('relu', name="sr_res_activation_" + str(id) + "_1")(x)

    #     x = Convolution2D(self.n, (self.f, self.f), activation='linear', padding='same',
    #                         name='sr_res_conv_' + str(id) + '_2')(x)

    #     Lambda(lambda x: x * self.scale_res)(x)
    #     m = Add(name="res_merge_" + str(id))([x, init])

    #     return m

	def _upsample(self, x):
		scale = self.scale
		assert scale in [2,3,4], 'scale should be 2, 3 or 4!'
		x = Convolution2D(self.n, (self.f, self.f), activation='linear', padding='same', name='sr_upsample_conv1')(x)
		if scale == 2:
			ps_features = (scale**2)
			x = Convolution2D(ps_features, (self.f, self.f), activation='linear', padding='same', name='sr_subpixel_conv1')(x)
			#x = slim.conv2d_transpose(x,ps_features,6,stride=1,activation='linear', padding='same', name='sr_subpixel_conv1')
			x = SubPixelUpscaling(r=scale, channels=self.channel)(x)
		elif scale == 3:
			ps_features =(scale**2)
			x = Convolution2D(ps_features, (self.f, self.f), activation='linear', padding='same', name='sr_subpixel_conv1')(x)
			#x = slim.conv2d_transpose(x,ps_features,9,stride=1,activation='linear', padding='same', name='sr_subpixel_conv1')
			x = SubPixelUpscaling(r=scale, channels=self.channel)(x)
		elif scale == 4:
			ps_features = (2**2)
			for i in range(2):
				x = Convolution2D(ps_features, (self.f, self.f), activation='linear', padding='same', name='sr_subpixel_conv%d'%(i+1))(x)
				#x = slim.conv2d_transpose(x,ps_features,6,stride=1,activation_fn=activation)
				x = SubPixelUpscaling(r=2, channels=self.channel)(x)
		return x
    
    

# Here is some changes
