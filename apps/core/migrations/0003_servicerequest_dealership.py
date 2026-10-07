from django.db import migrations, models
import django.db.models.deletion


def resolve_dealership(apps, schema_editor):
    ServiceRequest = apps.get_model("core", "ServiceRequest")
    pending = list(ServiceRequest.objects.filter(dealership__isnull=True))
    for request in pending:
        dealership_id = None
        if request.appointment_id:
            dealership_id = request.appointment.dealership_id
        if dealership_id is None:
            dealership_id = request.customer_vehicle.vehicle.dealership_id
        if dealership_id is None:
            raise RuntimeError(
                f"ServiceRequest {request.pk} has no resolvable dealership"
            )
        request.dealership_id = dealership_id
        request.save(update_fields=["dealership"])


def clear_dealership(apps, schema_editor):
    ServiceRequest = apps.get_model("core", "ServiceRequest")
    ServiceRequest.objects.update(dealership=None)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_alter_employee_role_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicerequest",
            name="dealership",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="service_requests",
                to="core.dealership",
            ),
        ),
        migrations.RunPython(resolve_dealership, clear_dealership),
        migrations.AlterField(
            model_name="servicerequest",
            name="dealership",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="service_requests",
                to="core.dealership",
            ),
        ),
        migrations.AddIndex(
            model_name="servicerequest",
            index=models.Index(
                fields=["dealership", "status"], name="service_req_dealer_status_idx"
            ),
        ),
    ]