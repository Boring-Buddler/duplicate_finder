# Datei-Duplikat-Finder

Dateien oder Ordner in zwei Listen laden und auf **Vergleichen** klicken. Über **Vergleich → Vergleichskriterien …** lassen sich mehrere Eigenschaften kombinieren: Dateiname, Dateiendung, Dateigröße, Änderungsdatum, relativer Pfad und Bearbeiter/Autor bei Office-Dateien. Ein Treffer muss **alle** ausgewählten Kriterien erfüllen. Namen und Pfade werden ohne Beachtung der Groß- und Kleinschreibung verglichen. Der relative Pfad beginnt jeweils am gewählten Ordner; das Änderungsdatum wird sekundengenau verglichen. Bei aktivem Bearbeiter-Kriterium werden Dateien ohne lesbare Office-Autorangabe als Fehler aufgeführt und nicht verglichen.

Optional kann der Dateiinhalt per SHA-256 geprüft werden. **Vor SHA-256 zuerst Dateigröße prüfen** spart das Lesen von Dateien, wenn in der anderen Liste kein Kandidat mit gleicher Größe und gleichen übrigen Kriterien liegt. Beim **SHA-256-Schwellenwert** lässt sich wählen, ob SHA-256 ab oder bis zur eingestellten Größe (jeweils einschließlich) verwendet wird. Dateien außerhalb dieses Bereichs werden nach Dateigröße und den übrigen Kriterien verglichen. Ohne Schwellenwert gilt SHA-256 für alle Dateien. Zum reinen Inhaltsvergleich alle anderen Kriterien abwählen und SHA-256 aktivieren.

Mit **Bericht erstellen** wird nach dem Vergleich ein Speicherort für einen HTML-Bericht abgefragt. Er enthält die gewählten Kriterien und SHA-256-Einstellungen, allgemeine Informationen, einen Schnellüberblick, die beiden Listen der nur jeweils dort vorkommenden Dateien und Baumansichten der Verzeichnisse.

In den Ergebnislisten sortiert ein Klick auf eine Spaltenüberschrift aufsteigend, der nächste absteigend. Ein Doppelklick auf einen Dateipfad öffnet die Datei im Windows-Explorer. Bei einem Treffer in beiden Listen werden die Pfade beider Listen geöffnet. Farbige Punkte markieren Kriterien, die auch einzeln in der anderen Liste erfüllt sind; die Farben lassen sich im Dialog **Vergleichskriterien** einstellen.

Über **Synchronisieren** zwischen den Dateibäumen lassen sich Ordner in beiden Listen mit Checkboxen auswählen. Ein markierter Ordner schließt seine Unterordner ein. Die App zeigt vor dem Kopieren eine Vorschau und kopiert fehlende Dateien samt Ordnerstruktur an denselben relativen Pfad in der jeweils anderen Liste. Vorhandene Dateien werden nicht überschrieben. Wenn mehrere Ordner pro Liste geladen sind, wird im Dialog je Liste eine Wurzel gewählt.

Für Drag-and-drop wird `tkinterdnd2` benötigt:

```powershell
python -m pip install -r requirements.txt
python duplicate_finder.py
```

Eine ausführbare Windows-Datei lässt sich mit `python -m PyInstaller --noconfirm DuplikatFinder.spec` erstellen.
