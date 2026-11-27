from datetime import datetime


def generate_document_number(prefix, depot_code, sequence):
    """
    Example:
    GRN-ABJ-20260814-0001
    LOAD-ABJ-20260814-0005
    """

    date_part = datetime.now().strftime("%Y%m%d")

    return f"{prefix}-{depot_code}-{date_part}-{sequence:04d}"

def next_sequence(model, field_name):
    """
    Returns the next sequence number for a model.
    """

    last_record = model.objects.order_by("-id").first()

    if not last_record:
        return 1

    return last_record.id + 1