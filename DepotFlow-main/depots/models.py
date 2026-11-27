from django.db import models


class Territory(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Depot(models.Model):
    territory = models.ForeignKey(
        Territory,
        on_delete=models.CASCADE,
        related_name='depots'
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.name