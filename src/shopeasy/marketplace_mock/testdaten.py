"""Testdaten fuer den Mock-Marktplatz (Issue #6).

Die Faelle stammen aus dem Vorgehenskonzept (Abschnitt 3.3) und werden in
spaeteren Sprints wiederverwendet:

- Normalfall innerhalb der Frist: AMZ-RET-001001, ZRET-2026-001001
  -> Happy Path (Sprint 4)
- Rueckgabefrist (30 Tage) ueberschritten: AMZ-RET-001002
  -> DMN "Berechtigung und Missbrauchsrisiko bewerten" (Sprint 4)
- Unklarer Freitext-Retourengrund: ZRET-2026-001002
  -> KI-Agent mit n8n (Sprint 5)
- Kunde mit auffaellig vielen Retouren: AMZ-RET-001003, ZRET-2026-001003,
  ZRET-2026-001004 -> Missbrauchsindikator (S5)
- Doppelte Meldung: entsteht in der Demo durch erneutes Senden einer Meldung
  (Issue #8) -> Dublettenpruefung, 409 Conflict (Issue #11)

Die Funktionen liefern bei jedem Aufruf frische Objekte, damit der Mock nach
einem Neustart wieder im Ausgangszustand ist.
"""

from shopeasy.marketplace_mock.formate import AmazonReturn, ZalandoReturn

VIELRETOURNIERER = "viel.retournierer@example.com"


def amazon_testdaten() -> list[AmazonReturn]:
    return [
        # Normalfall: 8 Tage nach Lieferung angemeldet
        AmazonReturn(
            returnId="AMZ-RET-001001",
            orderId="ORD-100234",
            buyerEmail="kundin@example.com",
            returnReasonCode="APPAREL_TOO_SMALL",
            customerComment="Faellt klein aus",
            deliveryDate="2026-10-20",
            requestedAt="2026-10-28T10:15:00Z",
            items=[{"sku": "PULLI-BLAU-M", "quantity": 1}],
        ),
        # Rueckgabefrist ueberschritten: 58 Tage nach Lieferung
        AmazonReturn(
            returnId="AMZ-RET-001002",
            orderId="ORD-099120",
            buyerEmail="spaet@example.com",
            returnReasonCode="UNWANTED_ITEM",
            deliveryDate="2026-09-01",
            requestedAt="2026-10-29T08:02:00Z",
            items=[{"sku": "JEANS-SLIM-32", "quantity": 1}],
        ),
        # Vielretournierer (1 von 3)
        AmazonReturn(
            returnId="AMZ-RET-001003",
            orderId="ORD-100410",
            buyerEmail=VIELRETOURNIERER,
            returnReasonCode="APPAREL_TOO_LARGE",
            deliveryDate="2026-10-24",
            requestedAt="2026-10-30T19:40:00Z",
            items=[
                {"sku": "PULLI-BLAU-M", "quantity": 1},
                {"sku": "SCHAL-GRAU", "quantity": 2},
            ],
        ),
    ]


def zalando_testdaten() -> list[ZalandoReturn]:
    return [
        # Normalfall: 7 Tage nach Lieferung angemeldet
        ZalandoReturn(
            id="ZRET-2026-001001",
            order={"number": "ORD-100301", "delivered_on": "22.10.2026"},
            customer={"email": "max@example.org"},
            reason={"code": 30, "text": "Farbe anders als auf dem Foto"},
            announced_on="29.10.2026",
            articles=[{"ean": "4012345000031", "qty": 1}],
        ),
        # Unklarer Freitext-Grund (Code 99), Fall fuer den KI-Agenten
        ZalandoReturn(
            id="ZRET-2026-001002",
            order={"number": "ORD-100322", "delivered_on": "25.10.2026"},
            customer={"email": "lena@example.org"},
            reason={
                "code": 99,
                "text": "naja irgendwie komisch, sitzt nicht so wie gedacht und "
                "die Naht ist vielleicht auch nicht ganz ok?",
            },
            announced_on="30.10.2026",
            articles=[{"ean": "4012345000048", "qty": 1}],
        ),
        # Vielretournierer (2 von 3)
        ZalandoReturn(
            id="ZRET-2026-001003",
            order={"number": "ORD-100415", "delivered_on": "26.10.2026"},
            customer={"email": VIELRETOURNIERER},
            reason={"code": 11, "text": ""},
            announced_on="31.10.2026",
            articles=[{"ean": "4012345000024", "qty": 1}],
        ),
        # Vielretournierer (3 von 3)
        ZalandoReturn(
            id="ZRET-2026-001004",
            order={"number": "ORD-100416", "delivered_on": "26.10.2026"},
            customer={"email": VIELRETOURNIERER},
            reason={"code": 10, "text": ""},
            announced_on="31.10.2026",
            articles=[
                {"ean": "4012345000055", "qty": 1},
                {"ean": "4012345000017", "qty": 1},
            ],
        ),
    ]
