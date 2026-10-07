from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def apply_changes(self, **fields):
        for name, value in fields.items():
            setattr(self, name, value)
        self.save(update_fields=[*fields, "updated_at"])
        return self
