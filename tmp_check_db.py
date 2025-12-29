import sqlite3, os
p='alibhi.db'
print('exists', os.path.exists(p))
if not os.path.exists(p):
    raise SystemExit
con=sqlite3.connect(p)
cur=con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('tables', [r[0] for r in cur.fetchall()])
try:
    cur.execute('PRAGMA table_info(pulizie)')
    cols=cur.fetchall()
    print('pulizie cols', cols)
    cur.execute('SELECT luogo, giorno, pulitore_1, pulitore_2, prossimo FROM pulizie')
    rows=cur.fetchall()
    print('pulizie rows', rows)
except Exception as e:
    print('pulizie error', e)
