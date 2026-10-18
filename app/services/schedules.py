"""Generacion del plan de cuotas (amortizacion) de una obligacion.

Simulado para la PoC: divide el monto en cuotas iguales segun la
periodicidad y la ultima cuota absorbe el remanente por redondeo.
No calcula intereses compuestos ni tablas de amortizacion reales.
"""

import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.enums import PaymentFrequency
from app.models.obligation import Obligation, PaymentSchedule

_MONTH_STEP = {
    PaymentFrequency.MONTHLY: 1,
    PaymentFrequency.QUARTERLY: 3,
    PaymentFrequency.SEMIANNUAL: 6,
    PaymentFrequency.ANNUAL: 12,
}


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _installment_dates(obligation: Obligation) -> list[date]:
    """Una cuota por periodo desde el origen; la ultima vence en due_date."""
    if obligation.payment_frequency == PaymentFrequency.ONE_TIME:
        return [obligation.due_date]
    step = _MONTH_STEP[obligation.payment_frequency]
    dates: list[date] = []
    i = 1
    while (d := _add_months(obligation.origin_date, step * i)) < obligation.due_date:
        dates.append(d)
        i += 1
    dates.append(obligation.due_date)
    return dates


def generate_schedule(db: Session, obligation: Obligation) -> list[PaymentSchedule]:
    """Crea las cuotas de la obligacion recien registrada."""
    dates = _installment_dates(obligation)
    n = len(dates)
    base = (obligation.amount / n).quantize(Decimal("0.01"))
    schedules: list[PaymentSchedule] = []
    for i, due in enumerate(dates, start=1):
        amount = base if i < n else obligation.amount - base * (n - 1)
        schedule = PaymentSchedule(
            obligation_id=obligation.id,
            installment_number=i,
            due_date=due,
            amount=amount,
        )
        db.add(schedule)
        schedules.append(schedule)
    return schedules
