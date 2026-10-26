
import getpass
from database import get_connection
from auth import hash_password

username = input("Enter existing admin username: ").strip()
new_password = getpass.getpass("Enter new password: ")

if len(new_password) < 8:
    print("Password must contain at least 8 characters.")
else:
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE admins
            SET password_hash = ?
            WHERE username = ?
            """,
            (hash_password(new_password), username),
        )
        connection.commit()

        if cursor.rowcount == 1:
            print("Admin password reset successfully.")
        else:
            print("Admin username not found.")

    finally:
        connection.close()
