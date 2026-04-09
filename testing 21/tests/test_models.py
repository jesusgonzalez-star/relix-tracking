from extensions import db
from models.tracking import DespachoTracking


def test_despacho_tracking_roundtrip(app_ctx):
    row = DespachoTracking(num_oc=92002, estado='INGRESADO')
    db.session.add(row)
    db.session.commit()
    assert row.id is not None

    found = DespachoTracking.query.filter_by(num_oc=92002).first()
    assert found is not None
    assert found.estado == 'INGRESADO'
