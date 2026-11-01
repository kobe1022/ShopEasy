"""Anfrage- und Antwortformate des Retouren-Service.

Das interne Modell (`NeueRetoure`, `Retoure`) liegt in `shopeasy.shared.models`.
Hier stehen nur die Formate, die der Service nach aussen anbietet.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from shopeasy.shared.models import (
    EMAIL_PATTERN,
    Artikel,
    Kanal,
    NeueRetoure,
    Retoure,
    StatusEintrag,
)


class WebshopAnmeldung(BaseModel):
    """Retourenanmeldung ueber das Webshop-Formular (Issue #10).

    Kanal und externe ID setzt der Service selbst: der Webshop gehoert zu
    ShopEasy, es gibt also keine fremde Meldungs-ID.
    """

    bestell_nr: str = Field(min_length=1, examples=["ORD-100300"])
    kunde_email: str = Field(pattern=EMAIL_PATTERN, examples=["max@example.org"])
    grund_text: str = Field(min_length=1, examples=["Farbe gefaellt nicht"])
    artikel: list[Artikel] = Field(min_length=1)

    def als_neue_retoure(self) -> NeueRetoure:
        """Ueberfuehrt die Anmeldung in das einheitliche Modell.

        Meldedatum ist der Tag der Anmeldung (fuer die Pruefung der Rueckgabefrist).
        """
        return NeueRetoure(
            kanal=Kanal.WEBSHOP,
            gemeldet_am=datetime.now(UTC).date(),
            **self.model_dump(),
        )


class RetoureMitHistorie(Retoure):
    """Antwort von GET /returns/{retouren_id} (Issue #14).

    Der Retourenvorgang plus alle Statuswechsel, aeltester zuerst. Damit sehen
    Kundenservice und Kund:in jederzeit, wo die Retoure steht (adressiert S2:
    keine Ende-zu-Ende-Transparenz).
    """

    historie: list[StatusEintrag]


class PollEintrag(BaseModel):
    """Eine abgeholte Marktplatz-Meldung und was mit ihr passiert ist."""

    marketplace: str
    externe_id: str
    retouren_id: str | None = None
    hinweis: str = ""


class PollErgebnis(BaseModel):
    """Antwort von POST /returns/poll (Issue #13).

    - angelegt: neue Retoure angelegt und beim Marktplatz quittiert
    - dubletten: Meldung war schon bekannt, nur quittiert (keine zweite Retoure)
    - manuell_pruefen: konnte nicht uebersetzt werden (z.B. unbekannte EAN), wird
      NICHT quittiert und taucht beim naechsten Abholen wieder auf
      (Soll-BPMN: "Anmeldung pruefen und vervollstaendigen")
    - nicht_erreichbar: Marktplaetze, die nicht geantwortet haben
    """

    angelegt: list[PollEintrag] = []
    dubletten: list[PollEintrag] = []
    manuell_pruefen: list[PollEintrag] = []
    nicht_erreichbar: list[str] = []
