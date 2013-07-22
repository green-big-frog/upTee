from django.contrib.auth.models import User
from django.db import models


def generate_random_key():
    return User.objects.make_random_password(length=16)


class TestingKey(models.Model):
    key = models.CharField(blank=True, max_length=16)
    is_used = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.key = generate_random_key()
        super(TestingKey, self).save(*args, **kwargs)
