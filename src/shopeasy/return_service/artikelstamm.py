"""Artikelstamm: Zuordnung EAN -> SKU (Issue #9).

Zalando meldet Artikel ueber die EAN (Strichcode), ShopEasy arbeitet intern mit
eigenen Artikelnummern (SKU). In der Praxis kommt diese Zuordnung aus dem ERP;
fuer den Prototyp reicht eine feste Tabelle mit den Artikeln aus den Testdaten.
"""

EAN_ZU_SKU: dict[str, str] = {
    "4012345000017": "PULLI-BLAU-M",
    "4012345000024": "JEANS-SLIM-32",
    "4012345000031": "SHIRT-WEISS-L",
    "4012345000048": "KLEID-ROT-S",
    "4012345000055": "SNEAKER-42",
    "4012345000062": "JACKE-SCHWARZ-L",
}


class UnbekannteEAN(LookupError):
    """Die EAN ist nicht im Artikelstamm.

    Soll-BPMN: Solche Meldungen gehen in "Anmeldung pruefen und vervollstaendigen"
    (manuelle Nacharbeit durch die Sachbearbeitung).
    """

    def __init__(self, ean: str) -> None:
        super().__init__(f"EAN {ean} ist nicht im Artikelstamm")
        self.ean = ean


def sku_fuer_ean(ean: str) -> str:
    """Liefert die ShopEasy-SKU zu einer EAN oder wirft `UnbekannteEAN`."""
    try:
        return EAN_ZU_SKU[ean]
    except KeyError:
        raise UnbekannteEAN(ean) from None
