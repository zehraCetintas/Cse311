# Program Outcome Tracker

A web-based system to manage and maintain **Program Outcome (PO) scores** of each student, built for Acıbadem University Computer Engineering (CSE 311 Software & CSE 321 Data Systems team project, Fall 2026).

Instructors enter assessment grades. The system turns them into Learning Outcome (LO) scores and then into Program Outcome (PO) scores, using the weights defined for each course:

```
Assessments ──(weight)──> Learning Outcomes ──(weight)──> Program Outcomes
score = Σ (weight × score) ÷ Σ weights
```

## Features

- **Roles:** department head, instructor, student
- **11 official Program Outcomes** of the department, loaded with one command
- **PO calculation engine:** assessment → LO → PO weighted averages
- **Bologna scraper:** imports courses, learning outcomes and assessment weights from Acıbadem OBS
- **Bulk grade import** from Excel (.xlsx), all-or-nothing in a single transaction
- **Demo data generator** for development and demos

## Tech stack

- Python 3.13, Django 6.1
- SQLite (development)
- openpyxl, requests, BeautifulSoup

## Getting started

```bash
git clone https://github.com/zehraCetintas/Cse311.git
cd Cse311

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver
```

Then open http://127.0.0.1:8000/.

## Demo data

`python manage.py seed_demo_data` creates the 11 POs, 4 courses (CSE 211, CSE 311, CSE 321, MAT 241) with learning outcomes, assessments and PO mappings, a department head, 2 instructors, 40 students and their grades.

| Role | Username | Password |
|---|---|---|
| Department head | `demo_head` | `demo12345` |
| Instructor (CSE 211, CSE 311) | `demo_instructor1` | `demo12345` |
| Instructor (CSE 321, MAT 241) | `demo_instructor2` | `demo12345` |
| Student | `900001` … `900040` | `demo12345` |

- The data is the same every time (fixed random seed). Running the command again replaces the previous demo data.
- Only demo data is touched: demo students have numbers starting with `9`, demo courses belong to the demo instructors. If a real course with the same code already exists, the command stops without changing anything.
- Options: `--students 200` (more students), `--seed 42` (different data), `--clear` (delete demo data only).

## Useful commands

| Command | What it does |
|---|---|
| `python manage.py load_program_outcomes` | Loads the 11 official Program Outcomes |
| `python manage.py seed_demo_data` | Creates demo courses, users, students and grades |
| `python manage.py scraper_course <url> [--course-code "CSE 311"]` | Imports a course syllabus from an Acıbadem Bologna (OBS) URL |
| `python manage.py test` | Runs the test suite |

## Working on the project

We use a feature-branch workflow:

- `main`: stable code
- `development`: integration branch; features are merged here first
- `feature/<name>`: one branch per feature, created from `development`

```bash
git switch development
git pull
git switch -c feature/my-feature
# ... make changes, then:
git add .
git commit -m "Describe the change"
git push -u origin feature/my-feature
```

Then open a pull request into `development` on GitHub and ask a teammate to review it.

## Team

- Zehra Çetintaş ([@zehraCetintas](https://github.com/zehraCetintas))
- Uygar Keçeli ([@UygarK27](https://github.com/UygarK27))
- [@burak671](https://github.com/burak671)
- [@adaag7](https://github.com/adaag7)
