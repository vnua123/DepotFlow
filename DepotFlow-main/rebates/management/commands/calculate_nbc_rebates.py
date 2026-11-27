from django.core.management.base import BaseCommand, CommandError
from depots.models import Depot
from rebates.services import calculate_monthly_rebates

class Command(BaseCommand):
    help = 'Calculate monthly NBC rebate estimates using the placement effective for the selected month.'
    def add_arguments(self, parser):
        parser.add_argument('--depot-code', required=True)
        parser.add_argument('--year', type=int, required=True)
        parser.add_argument('--month', type=int, required=True)
    def handle(self, *args, **opts):
        if not 1 <= opts['month'] <= 12:
            raise CommandError('--month must be between 1 and 12')
        try:
            depot = Depot.objects.get(code=opts['depot_code'])
        except Depot.DoesNotExist:
            raise CommandError('No depot found with that code')
        records = calculate_monthly_rebates(depot, opts['year'], opts['month'])
        self.stdout.write(self.style.SUCCESS(f'{depot.name}: {len(records)} monthly category estimate(s) calculated using the effective quarterly placement.'))
