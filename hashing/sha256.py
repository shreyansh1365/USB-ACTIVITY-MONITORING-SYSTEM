import hashlib
import time


def calculate_sha256(file_path, retries=5, delay=1):

    for attempt in range(retries):

        try:
            sha256_hash = hashlib.sha256()

            with open(file_path, "rb") as file:

                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    sha256_hash.update(chunk)

            return sha256_hash.hexdigest()

        except (PermissionError, FileNotFoundError, OSError) as error:

            if attempt < retries - 1:
                time.sleep(delay)

            else:
                print(f"SHA256 skipped: {file_path}")
                print(f"Reason: {error}")
                return None