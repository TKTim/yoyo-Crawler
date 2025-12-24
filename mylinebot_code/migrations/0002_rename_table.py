# Rename table from foodlinebot_parsedarticle to mylinebot_code_parsedarticle

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('mylinebot_code', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelTable(
            name='parsedarticle',
            table='mylinebot_code_parsedarticle',
        ),
    ]
