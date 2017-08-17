from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.conf import settings
import os
from django.db.models import Max

from PIL import Image as Img
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile
from images.storage import OverwriteStorage
from django.utils.translation import ugettext_lazy as _
import uuid

from django.db.models.signals import post_save, post_delete
from django.dispatch.dispatcher import receiver

from rest_framework.exceptions import APIException
from django.core.exceptions import ObjectDoesNotExist

from django.contrib.auth import get_user_model

User = get_user_model()


def user_directory_path_profile(instance, filename):
    # file will be uploaded to MEDIA_ROOT/profile_images/user_<id>/<filename>
    return 'profile_images/user_%s/%s' % (instance.user.id, filename)


class ProfileImage(models.Model):

    ORDER_CHOICES = (
        (0, 'First image'),
        (1, 'Second image'),
        (2, 'Third image'),
        (3, 'Fourth image'),
        (4, 'Fifth image'),
        (5, 'Sixth image'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL)
    image = models.ImageField(upload_to=user_directory_path_profile,
                              storage=OverwriteStorage())
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    class Meta:
        verbose_name = _('Profile Image')
        verbose_name_plural = _('Profile Images')

    def __str__(self):
        return '%s' % self.user

    def save(self, *args, **kwargs):
        # check that user doesn't have 6 profile_images, raise error otherwise
        profile_imgs = ProfileImage.objects.filter(user=self.user)

        if len(profile_imgs) >= 6:
            raise TooManyImages

        # compress image before saving
        if self.image and self.pk is None:
            img = Img.open(BytesIO(self.image.read()))

            if img.mode != 'RGB':
                img = img.convert('RGB')

            img.thumbnail(
                (self.image.width / 1.5, self.image.height / 1.5),
                Img.ANTIALIAS
            )
            output = BytesIO()

            img.save(output, format='JPEG', quality=25)
            self.image = InMemoryUploadedFile(
                output, 'ImageField', "%s.jpg" % (self.uuid),
                'image/jpeg', output.seek(0, os.SEEK_END), None
            )

        # save
        super(ProfileImage, self).save()


class ProfileImageOrder(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL)
    order = ArrayField(
        models.IntegerField(null=True, blank=True),
        size=6,
        default=[],
        blank=True
    )

    def __str__(self):
        return '%s' % self.user

    def add(self, profile_image_id):
        if profile_image_id in self.order:
            raise DuplicateImage

        self.order.append(profile_image_id)
        self.save()

    def move(self, new_position, profile_image_id):
        try:
            self.order.remove(profile_image_id)
        except ValueError:
            raise ImageNotAvailable

        self.order.insert(new_position, profile_image_id)
        self.save()

    def drop(self, profile_image_id):
        self.order.remove(profile_image_id)
        self.save()

    def get_images(self):
        return Profile.objects.filter(id__in=self.order)


# Signals

def _pio_helper_create(**kwargs):
    return ProfileImageOrder.objects.get_or_create(**kwargs)


def _pio_helper_get(**kwargs):
    return ProfileImageOrder.objects.get(**kwargs)


@receiver(post_save, sender=User)
def user_create(sender, instance, created, **kwargs):
    if created:
        obj, created_pio = _pio_helper_create(user=instance)


@receiver(post_delete, sender=User)
def user_delete(sender, instance, **kwargs):
    obj, created_pio = _pio_helper_get(user=instance)
    obj.delete()


@receiver(post_save, sender=ProfileImage)
def profile_image_create(sender, instance, created, **kwargs):
    if created:
        obj, created_pio = _pio_helper_create(user=instance.user)
        obj.add(instance.id)


@receiver(post_delete, sender=ProfileImage)
def profile_image_delete(sender, instance, **kwargs):
    # delete actual image file
    instance.image.delete(False)

    # drop image from the order element
    obj = _pio_helper_get(user=instance.user)
    obj.drop(instance.id)


class TooManyImages(APIException):
    status_code = 401
    default_detail = "You may only have 6 profile pictures at a time."
    default_code = 'profile_pic_max_exceeded'


class DuplicateImage(APIException):
    status_code = 400
    default_detail = "You cannot submit the same image twice."
    default_code = 'duplicate_image'


class ImageNotAvailable(APIException):
    status_code = 400
    default_detail = "Image being referenced is not available."
    default_code = 'image_not_available'
