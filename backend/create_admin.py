import getpass
import sqlite3
from database import get_connection
from auth import hash_password

def create_admin():
    name=input("enter username : ").strip()
    if len(name)<3:
        print("username must contain atleast 3 characters")
        return
    password_hash=getpass.getpass("enter password : ")
    if password_hash=="":
        print("password cannot be empty")
        return
    password_hash=hash_password(password_hash)
    try:
        connection=get_connection()
        connection.execute(
        "INSERT INTO admins (username,password_hash) VALUES(?,?)",
        (name,password_hash)
    )
        connection.commit()
        print("admin account created successfully")
    except sqlite3.IntegrityError:
        connection.rollback()
        print("Username already exists or a database constraint was violated.")
    except sqlite3.Error as error:
        connection.rollback()
        print("Database error:", error)


if __name__ == "__main__":
    create_admin()
