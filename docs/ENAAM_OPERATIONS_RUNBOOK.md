# Enaam operations

How the desk is run today. A restore has not been drilled. That drill is a later phase.

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

Stop the desk, then copy the database file and keep the copy off the machine. Start the desk again. A copy taken while the process is writing can be checked with `sqlite3 khursheed.db "PRAGMA integrity_check;"`. `-wal` and `-shm` files belong with the copy if the desk was not stopped. This copy step has not been rehearsed against a restore.

## Restore

Stop the desk. Replace `khursheed.db` with the copy. Start the desk. Confirm a known bill or decision is still listed before deleting the previous file. This has not been rehearsed.

## Morning

The Mac cron that ran every minute has been removed. The Monday weekly summary cron may still be installed. On Railway the image runs Streamlit. A separate `morning_watch.py` loop is not started by the laptop command.

## Health

`GET /_stcore/health` is the Railway check. A page that asks for the password is a running desk. A running page is not proof that the tests passed.
