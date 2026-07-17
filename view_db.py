import sqlite3

db = sqlite3.connect("database.db")
cursor = db.cursor()

cursor.execute("SELECT * FROM members")

rows = cursor.fetchall()

print("\nDATABASE CONTENT:\n")

for row in rows:
    print(row)