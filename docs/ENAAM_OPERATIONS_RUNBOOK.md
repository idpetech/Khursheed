# Enaam operations

How the desk is run today. The copy command below was checked once on the laptop. The live file was not replaced, and no copy was kept. The Railway volume was not copied.

## Run

From the project directory:

```
.venv/bin/python -m streamlit run hey_eman_app.py --server.port 8510 --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false
```

Open http://localhost:8510 and enter `KHURSHEED_UI_PASSWORD`.

Do not run `scripts/start_enaam_services.sh`. It starts a different stack and can treat port 8510 as a conflict.

## Code changes

Streamlit does not reload this app. Stop the process listening on 8510, then start the command above. The owner must sign in again.

## Config that must stay

The bills and subscriptions list is in the sidebar Config, inside the scrolling settings, under "Days of mail to scan". Mail and Now show results. Do not move or remove that list without explicit consent.

## Data

The laptop database is `khursheed.db` in the project directory. Railway uses `KHURSHEED_DB_PATH=/data/khursheed.db` on a volume. They are not the same file. Do not copy one over the other unless the intent is to replace it.

## Backup

The laptop file is `khursheed.db` in the project directory. On Railway the file is `/data/khursheed.db` because `KHURSHEED_DB_PATH` is set in the image. A git push does not copy either file. Keep a Railway copy off the volume, and keep a laptop copy outside this project. Putting one file in the other's place replaces that database.

From the project directory, with the desk running or stopped:

```
sqlite3 khursheed.db ".backup 'khursheed-copy.db'"
sqlite3 khursheed-copy.db "PRAGMA integrity_check;"
```

`integrity_check` should print `ok`. Move `khursheed-copy.db` off the machine, then delete the copy that was left in the project directory. `.backup` includes committed pages, so the `-wal` and `-shm` files do not need to travel with it.

On the Railway service the same two commands use `/data/khursheed.db`. Take the resulting file off the volume. Leave the laptop file where it is.

On 22 Nov 2026 the laptop command was run into a temporary file. `integrity_check` printed `ok`. That file was deleted. Nothing was kept off the machine, and `/data/khursheed.db` was not read.

## Restore

This replacement has not been performed.

Stop the process that has the file open. On the laptop that is the listener on port 8510. On Railway that is the Khursheed service.

Move the current `khursheed.db`, `khursheed.db-wal`, and `khursheed.db-shm` aside. Do not delete them yet. On Railway those names are under `/data`.

Put the backup in place as `khursheed.db` (on Railway, `/data/khursheed.db`). Start the desk and sign in. Confirm a bill or a decision you already know is still listed. After that, the files you moved aside can be deleted.

A page that loads is not that confirmation. The known row is.

## Morning

The Mac cron that ran every minute has been removed. The Monday weekly summary cron may still be installed. On Railway the image runs Streamlit. A separate `morning_watch.py` loop is not started by the laptop command.

## Health

`GET /_stcore/health` is the Railway check. A page that asks for the password is a running desk. A running page is not proof that the tests passed.
