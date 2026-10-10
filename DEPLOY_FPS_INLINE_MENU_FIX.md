# Hotfix: Inline-Menüs / SQLite group_settings

## Ursache

Die laufende Datenbank hat ein gemischtes Schema: `join_check` fehlt, aber
`bot_welcome_active` ist bereits vorhanden. Die bisherige Fehlerbehandlung
versucht bei jedem `OperationalError` pauschal alle drei neueren Spalten
hinzuzufügen. SQLite bricht beim ersten bereits vorhandenen Spaltennamen ab.

## Dateien

- `inline_menu_db_fix.py`: wiederholbar ausführbare Schema-Prüfung und
  korrigierte `get_settings`-/`update_setting`-Implementierungen.

## Deployment auf fps.ms

Diese Änderung ist noch **nicht automatisch auf fps.ms deployed**. Das Hosting
ist nicht mit diesem GitHub-Zugang verbunden. Außerdem muss die Datei in die
tatsächlich laufende `main.py` integriert werden; ein zusätzliches Python-
Modul allein ändert die Handler nicht.

1. Stoppe den Bot.
2. Sichere `house_bot.db` (nicht löschen).
3. Öffne in fps.ms die tatsächlich laufende `main.py`.
4. Übernimm aus `inline_menu_db_fix.py` die Konstante
   `SETTINGS_DEFAULTS` und die drei Funktionen
   `ensure_group_settings_schema`, `get_settings`, `update_setting`.
   Passe bei Bedarf den Aufruf so an, dass `get_settings(chat_id)` den
   bestehenden globalen `DB_FILE` verwendet.
5. Speichere und starte genau eine Bot-Instanz.
6. Teste Gruppenauswahl, Öffnen der Einstellungen und Umschalten eines Schalters.

**Wichtig:** Der aktuelle `main.py` auf GitHub `main` ist nicht derselbe
vollständige Stand wie der von fps.ms (der gepostete Traceback zeigt Zeile 915,
während GitHub einen wesentlich kürzeren Stand enthält). Daher wird die
Produktionsdatei hier bewusst nicht überschrieben, um andere Bot-Funktionen
nicht versehentlich zu entfernen.
