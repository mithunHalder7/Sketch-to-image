# -*- coding: utf-8 -*-
"""Copy of hands_on_pixtopix4.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/15spkueh9y_XN6Je9F36Y4Qnw4yIBIj1P
"""

import tensorflow as tf
from tensorflow.keras import layers, Model
from tensorflow.keras.activations import relu, tanh
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.callbacks import ModelCheckpoint, EarlyStopping
from tensorflow.keras.losses import BinaryCrossentropy
from tensorflow.keras.optimizers import RMSprop, Adam
from tensorflow.keras.metrics import binary_accuracy
import tensorflow_datasets as tfds
#from tensorflow_addons.layers import InstanceNormalization
!pip install tensorflow-addons==0.16.1
import tensorflow_addons as tfa

import numpy as np
import matplotlib.pyplot as plt
import os

import warnings
warnings.filterwarnings('ignore')
print("Tensorflow", tf.__version__)
from packaging.version import parse as parse_version
assert parse_version(tf.__version__) <= parse_version("2.9.2"), \
    f"Please install TensorFlow version 2.6.0 or older. Your current version is {tf.__version__}."

#_URL = 'https://github.com/PacktPublishing/Hands-On-Image-Generation-with-TensorFlow-2.0/releases/download/facades/facades.tar.gz'

#path_to_zip = tf.keras.utils.get_file('facades.tar.gz',origin=_URL, extract=True)

#PATH = os.path.join(os.path.dirname(path_to_zip), 'facades/')
from google.colab import drive
drive.mount('/content/drive/')

image_shape = (256, 256, 3)
IMG_HEIGHT = image_shape[0]
IMG_WIDTH = image_shape[1]

PATH = '/content/drive/MyDrive/cuck_image_3'

BATCH_SIZE = 1
BUFFER_SIZE = 400

def load(image_file):
    image = tf.io.read_file(image_file)
    image = tf.image.decode_jpeg(image)

    w = tf.shape(image)[1]

    w = w // 2
    real_image = image[:, :w, :]
    input_image = image[:, w:, :]

    input_image = tf.cast(input_image, tf.float32)
    real_image = tf.cast(real_image, tf.float32)

    return input_image, real_image

def resize(input_image, real_image, height, width):
    input_image = tf.image.resize(input_image, [height, width],
                                method=tf.image.ResizeMethod.NEAREST_NEIGHBOR)
    real_image = tf.image.resize(real_image, [height, width],
                               method=tf.image.ResizeMethod.NEAREST_NEIGHBOR)

    return input_image, real_image

def random_crop(input_image, real_image):
    stacked_image = tf.stack([input_image, real_image], axis=0)
    cropped_image = tf.image.random_crop(
      stacked_image, size=[2, IMG_HEIGHT, IMG_WIDTH, 3])

    return cropped_image[0], cropped_image[1]

def normalize(input_image, real_image):
    input_image = (input_image / 127.5) - 1
    real_image = (real_image / 127.5) - 1

    return input_image, real_image

@tf.function()
def random_jitter(input_image, real_image):
    # resizing to 286 x 286 x 3
    input_image, real_image = resize(input_image, real_image, 286, 286)

    # randomly cropping to 256 x 256 x 3
    input_image, real_image = random_crop(input_image, real_image)

    if tf.random.uniform(()) > 0.5:
        # random mirroring
        input_image = tf.image.flip_left_right(input_image)
        real_image = tf.image.flip_left_right(real_image)

    return input_image, real_image

def load_image_train(image_file):
    input_image, real_image = load(image_file)
    input_image, real_image = random_jitter(input_image, real_image)
    input_image, real_image = normalize(input_image, real_image)

    return input_image, real_image

def load_image_test(image_file):
    input_image, real_image = load(image_file)
    input_image, real_image = resize(input_image, real_image,
                                   IMG_HEIGHT, IMG_WIDTH)
    input_image, real_image = normalize(input_image, real_image)

    return input_image, real_image

train_dataset = tf.data.Dataset.list_files('/content/drive/MyDrive/cuck_image_3/output/*.jpg')
train_dataset = train_dataset.map(load_image_train,
                                  num_parallel_calls=tf.data.experimental.AUTOTUNE)
train_dataset = train_dataset.shuffle(BUFFER_SIZE)
train_dataset = train_dataset.batch(BATCH_SIZE).repeat()

test_dataset = tf.data.Dataset.list_files('/content/drive/MyDrive/cuhk_images_2/merged_test2/*.jpg')
test_dataset = test_dataset.map(load_image_test)
test_dataset = test_dataset.batch(BATCH_SIZE).repeat()

epocch_list=[]
generator_loss_list=[]
descrim_loss_list=[]

class PIX2PIX():
    def __init__(self, input_shape):
        self.input_shape = input_shape

        # discriminator
        self.discriminator = self.build_discriminator()
        self.discriminator.trainable = False
        self.optimizer_discriminator = Adam(2e-4, 0.5, 0.9999)
                
        # build generator pipeline with frozen discriminator
        self.generator = self.build_generator()
        discriminator_output = self.discriminator([self.generator.input, 
                                                   self.generator.output])
        self.patch_size = discriminator_output.shape[1]
        self.model = Model(self.generator.input, [discriminator_output, self.generator.output])
        self.LAMBDA = 100
        self.model.compile(loss = ['bce','mae'],
                           optimizer = Adam(2e-4, 0.5, 0.9999),
                           loss_weights=[1, self.LAMBDA])
        self.discriminator.trainable = True
        self.bce = tf.keras.losses.BinaryCrossentropy()
        
    def bce_loss(self, y_true, y_pred):
        
        loss = self.bce(y_true, y_pred)

        return loss
    
    def downsample(self, channels, kernels, strides=2, norm=True, activation=True, dropout=False):
        initializer = tf.random_normal_initializer(0., 0.02)
        block = tf.keras.Sequential()
        block.add(layers.Conv2D(channels, kernels, strides=strides, padding='same', 
                                use_bias=False, kernel_initializer=initializer))

        if norm:
            block.add(tfa.layers.InstanceNormalization(axis=1, center=True,
                                                   scale=True))              
        if activation:
            block.add(layers.LeakyReLU(0.2)) 
        if dropout:
            block.add(layers.Dropout(0.5))

        return block

    def upsample(self, channels, kernels, strides=1, norm=True, activation=True, dropout=False):
        initializer = tf.random_normal_initializer(0., 0.02)
        block = tf.keras.Sequential()
        block.add(layers.UpSampling2D((2,2)))
        block.add(layers.Conv2D(channels, kernels, strides=strides, padding='same', 
                                use_bias=False, kernel_initializer=initializer))

        if norm:
            block.add(tfa.layers.InstanceNormalization(axis=1, center=True,
                                                   scale=True))              
        if activation:
            block.add(layers.LeakyReLU(0.2)) 
        if dropout:
            block.add(layers.Dropout(0.5))

        return block

    def build_generator(self):

        DIM = 64

        input_image = layers.Input(shape=image_shape)
        down1 = self.downsample(DIM, 4, norm=False)(input_image) # 128, DIM
        down2 = self.downsample(2*DIM, 4)(down1) # 64, 2*DIM
        down3 = self.downsample(4*DIM, 4)(down2) # 32, 4*DIM
        down4 = self.downsample(4*DIM, 4)(down3) # 16, 4*DIM
        down5 = self.downsample(4*DIM, 4)(down4) # 8, 4*DIM
        down6 = self.downsample(4*DIM, 4)(down5) # 4, 4*DIM
        down7 = self.downsample(4*DIM, 4)(down6) # 2, 4*DIM


        up6 = self.upsample(4*DIM, 4, dropout=True)(down7) # 4,4*DIM
        concat6 = layers.Concatenate()([up6, down6])   

        up5 = self.upsample(4*DIM, 4, dropout=True)(concat6) 
        concat5 = layers.Concatenate()([up5, down5]) 

        up4 = self.upsample(4*DIM, 4, dropout=True)(concat5) 
        concat4 = layers.Concatenate()([up4, down4]) 

        up3 = self.upsample(4*DIM, 4)(concat4) 
        concat3 = layers.Concatenate()([up3, down3]) 

        up2 = self.upsample(2*DIM, 4)(concat3) 
        concat2 = layers.Concatenate()([up2, down2]) 

        up1 = self.upsample(DIM, 4)(concat2) 
        concat1 = layers.Concatenate()([up1, down1]) 

        output_image = tanh(self.upsample(3, 4, norm=False, activation=False)(concat1))

        return Model(input_image, output_image, name='generator')         
    
    def build_discriminator(self):
        DIM = 64
        model = tf.keras.Sequential(name='discriminators') 
        input_image_A = layers.Input(shape=image_shape)
        input_image_B = layers.Input(shape=image_shape)
        
        x = layers.Concatenate()([input_image_A, input_image_B])
        x = self.downsample(DIM, 4, norm=False)(x) # 128
        x = self.downsample(2*DIM, 4)(x) # 64
        x = self.downsample(4*DIM, 4)(x) # 32
        x = self.downsample(8*DIM, 4, strides=1)(x) # 29
        output = layers.Conv2D(1, 4, activation='sigmoid')(x)

        return Model([input_image_A, input_image_B], output)     
    
    def train_discriminator(self, real_images_A, real_images_B, batch_size):
        real_labels = tf.ones((batch_size, self.patch_size, self.patch_size, 1))
        fake_labels = tf.zeros((batch_size, self.patch_size, self.patch_size, 1))
                  
        fake_images_B = self.generator.predict(real_images_A)
        
        with tf.GradientTape() as gradient_tape:
            
            # forward pass
            pred_fake = self.discriminator([real_images_A, fake_images_B])
            pred_real = self.discriminator([real_images_A, real_images_B])
            
            # calculate losses
            loss_fake = self.bce_loss(fake_labels, pred_fake)
            loss_real = self.bce_loss(real_labels, pred_real)           
            
            # total loss
            total_loss = 0.5*(loss_fake + loss_real)
            
            # apply gradients
            gradients = gradient_tape.gradient(total_loss, self.discriminator.trainable_variables)
            
            self.optimizer_discriminator.apply_gradients(zip(gradients, self.discriminator.trainable_variables))

        return loss_fake, loss_real
    
    def train(self, data_generator, test_data_generator, batch_size, steps, interval=100):
        val_images = next(test_data_generator) 
        real_labels = tf.ones((batch_size, self.patch_size, self.patch_size, 1))
        self.batch_size = batch_size
        for i in range(steps):
            epocch_list.append(i)
    
            real_images_A, real_images_B = next(data_generator)
            loss_fake, loss_real = self.train_discriminator(real_images_A, real_images_B, batch_size)
            discriminator_loss = 0.5*(loss_fake + loss_real)
            descrim_loss_list.append(discriminator_loss)
                
            # train generator
            g_loss = self.model.train_on_batch(real_images_A, [real_labels, real_images_B])
            generator_loss_list.append(g_loss)



            if i%interval == 0:
                msg = "Step {}: discriminator_loss {:.4f} g_loss {:.4f}"\
                .format(i, discriminator_loss, g_loss[0])
                print(msg)
                
                fake_images = self.generator.predict(val_images[0])
                self.plot_images(val_images, fake_images)
            
    def plot_images(self, real_images, fake_images):   
        grid_row = min(fake_images.shape[0], 4)
        grid_col = 3
        f, axarr = plt.subplots(grid_row, grid_col, figsize=(grid_col*6, grid_row*6))
        for row in range(grid_row):
            ax = axarr if grid_row==1 else axarr[row]
            ax[0].imshow((real_images[0][row]+1)/2)
            ax[0].axis('off') 
            ax[1].imshow((real_images[1][row]+1)/2)
            ax[1].axis('off') 
            ax[2].imshow((fake_images[row]+1)/2)
            ax[2].axis('off') 
        plt.show()
        
    def sample_images(self, number):
        z = tf.random.normal((number, self.z_dim))
        images = self.generator.predict(z)
        self.plot_images(images)
        return images
    
pix2pix = PIX2PIX(image_shape)

tf.keras.utils.plot_model(pix2pix.generator, show_shapes=True)

tf.keras.utils.plot_model(pix2pix.discriminator, show_shapes=True)

"""pix2pix.train(iter(train_dataset), iter(test_dataset), BATCH_SIZE, 100, 10)

"""

pix2pix.train(iter(train_dataset), iter(test_dataset), BATCH_SIZE, 500, 10)

test_iterator = iter(test_dataset)
fake_images_list = []

for _ in range(4):
    val_images = next(test_iterator) 
    fake_images = pix2pix.generator.predict(val_images[0])
    fake_images_list.append(fake_images)
    pix2pix.plot_images(val_images, fake_images)

from math import floor
from numpy import ones
from numpy import expand_dims
from numpy import log
from numpy import mean
from numpy import std
from numpy import exp
from keras.applications.inception_v3 import InceptionV3
from keras.applications.inception_v3 import preprocess_input



def calculate_inception_score(images, n_split=10, eps=1E-16):
	# load inception v3 model
	model = InceptionV3()
	# convert from uint8 to float32
	processed = images.astype('float32')
	# pre-process raw images for inception v3 model
	processed = preprocess_input(processed)
	# predict class probabilities for images
	yhat = model.predict(processed)
	# enumerate splits of images/predictions
	scores = list()
	n_part = floor(images.shape[0] / n_split)
 
	for i in range(n_split):
		# retrieve p(y|x)
		ix_start, ix_end = i * n_part, i * n_part + n_part
		p_yx = yhat[ix_start:ix_end]
		# calculate p(y)
		p_y = expand_dims(p_yx.mean(axis=0), 0)
		# calculate KL divergence using log probabilities
		kl_d = p_yx * (log(p_yx + eps) - log(p_y + eps))
		# sum over classes
		sum_kl_d = kl_d.sum(axis=1)
		# average over images
		avg_kl_d = mean(sum_kl_d)
		# undo the log
		is_score = exp(avg_kl_d)
		# store
		scores.append(is_score)
	# average across images
	is_avg, is_std = mean(scores), std(scores)
	return is_avg, is_std

# pretend to load images
fake_images = ones((50, 299, 299, 3))
print('loaded', fake_images.shape)
# calculate inception score
is_avg, is_std = calculate_inception_score(fake_images)
print('score', is_avg, is_std)

g_loss_list=[]
d_loss_list=[]


#print(epocch_list)
#print(descrim_loss_list)
#print(generator_loss_list)



for i in range(len(generator_loss_list)):
  for j in range(1):
    #print(generator_loss_list[i][0])
    
    g_loss_list.append(generator_loss_list[i][0])

 

for i in descrim_loss_list:
  d_loss_list.append(i.numpy().tolist())
  

print(g_loss_list)
print(d_loss_list) 

print(len(d_loss_list))
print(len(g_loss_list))

plt.plot(epocch_list,g_loss_list)
plt.xlabel('number of epochs')
plt.ylabel('generator loss')
plt.title("Genarator loss")
plt.show()


plt.plot(epocch_list,d_loss_list)
plt.xlabel('number of epochs')
plt.ylabel('discriminator loss')
plt.title("Discriminator loss")
plt.show()