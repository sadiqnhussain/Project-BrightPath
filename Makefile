.PHONY: install migrations migrate check test run demo
install:
	python -m pip install -r requirements.txt
migrations:
	python manage.py makemigrations core
migrate:
	python manage.py migrate
check:
	python manage.py check

test:
	python manage.py test
run:
	python manage.py runserver
demo:
	python manage.py seed_demo --password 'ChangeThis-Demo-Password-2026'
