import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.db import transaction

from main.models import Assessment, Course, LearningOutcome


class BolognaScraperService:
    @staticmethod
    def scrape_course_data(url: str, course_code: str | None = None):
        """Scrape one course page or every course listed in a curriculum."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/118.0.0.0 Safari/537.36"
            )
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            parsed_url = urlparse(url)
            if parsed_url.path.lower().endswith("/index.aspx"):
                query = parse_qs(parsed_url.query)
                if query.get("curOp", [""])[0].lower() == "showpac":
                    listing_url = urljoin(url, "progCourses.aspx")
                    listing_url = f"{listing_url}?{urlencode({
                        'lang': query.get('lang', ['en'])[0],
                        'curSunit': query.get('curSunit', [''])[0],
                    })}"
                    listing_response = requests.get(
                        listing_url, headers=headers, timeout=10
                    )
                    listing_response.raise_for_status()
                    listed_courses = BolognaScraperService._find_courses(
                        BeautifulSoup(listing_response.content, "html.parser"),
                        listing_url,
                        course_code=course_code,
                    )
                    if not listed_courses:
                        selection = (
                            f" matching course {course_code!r}"
                            if course_code
                            else ""
                        )
                        return BolognaScraperService._failure(
                            f"No courses{selection} were found in the program listing."
                        )

                    courses = []
                    for listed_course in listed_courses:
                        detail_response = requests.get(
                            listed_course["url"], headers=headers, timeout=10
                        )
                        detail_response.raise_for_status()
                        course_result = BolognaScraperService.parse_html_content(
                            BeautifulSoup(detail_response.content, "html.parser")
                        )
                        data = course_result["data"]
                        data["course_code"] = (
                            data["course_code"] or listed_course["course_code"]
                        )
                        data["course_title"] = (
                            data["course_title"] or listed_course["course_title"]
                        )
                        courses.append(data)

                    if course_code:
                        return {
                            "success": True,
                            "error": None,
                            "data": courses[0],
                        }
                    return {
                        "success": True,
                        "error": None,
                        "courses": courses,
                    }
        except requests.RequestException as exc:
            return BolognaScraperService._failure(
                f"Failed to retrieve page: {exc}"
            )

        return BolognaScraperService.parse_html_content(
            BeautifulSoup(response.content, "html.parser")
        )

    @staticmethod
    def _failure(message: str):
        return {"success": False, "error": message, "data": None}

    @staticmethod
    def _normalize_course_code(value: str) -> str:
        return re.sub(r"\s+", "", value).casefold()

    @staticmethod
    def _find_courses(
        soup: BeautifulSoup, listing_url: str, course_code: str | None = None
    ) -> list[dict[str, str]]:
        wanted_code = (
            BolognaScraperService._normalize_course_code(course_code)
            if course_code
            else None
        )
        language = parse_qs(urlparse(listing_url).query).get("lang", ["en"])[0]
        courses = []
        seen_ids = set()

        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"], recursive=False)
            code_match = next(
                (
                    match
                    for cell in cells
                    if (match := re.search(
                        r"\b([A-Z][A-Z0-9]{1,9}\s*\d{2,4})\b",
                        cell.get_text(" ", strip=True),
                        re.IGNORECASE,
                    ))
                ),
                None,
            )
            if code_match is None:
                continue

            code = re.sub(r"\s+", "", code_match.group(1))
            if wanted_code and (
                BolognaScraperService._normalize_course_code(code) != wanted_code
            ):
                continue

            course_id = None
            for link in row.find_all("a"):
                match = re.search(
                    r"prolizOpenCourseDetails\(\s*(\d+)\s*\)",
                    link.get("onclick", ""),
                    re.IGNORECASE,
                )
                if match:
                    course_id = match.group(1)
                    break
            if not course_id or course_id in seen_ids:
                continue

            code_cell_index = next(
                (
                    index
                    for index, cell in enumerate(cells)
                    if re.search(
                        r"\b[A-Z][A-Z0-9]{1,9}\s*\d{2,4}\b",
                        cell.get_text(" ", strip=True),
                        re.IGNORECASE,
                    )
                ),
                None,
            )
            title = (
                cells[code_cell_index + 1].get_text(" ", strip=True)
                if code_cell_index is not None and code_cell_index + 1 < len(cells)
                else ""
            )
            detail_url = urljoin(listing_url, "progCourseDetails.aspx")
            courses.append(
                {
                    "course_code": code,
                    "course_title": title,
                    "url": f"{detail_url}?{urlencode({
                        'curCourse': course_id,
                        'lang': language,
                    })}",
                }
            )
            seen_ids.add(course_id)

        return courses

    @staticmethod
    def parse_html_content(soup: BeautifulSoup):
        """Extract course identity, learning outcomes, and assessment weights."""
        data = {
            "course_code": "",
            "course_title": "",
            "learning_outcomes": [],
            "assessments": [],
        }

        course_table = soup.find("table", id="grdDers")
        if course_table:
            rows = course_table.find_all("tr")
            if len(rows) > 1:
                headers = [
                    cell.get_text(" ", strip=True).casefold()
                    for cell in rows[0].find_all(["th", "td"])
                ]
                values = [
                    cell.get_text(" ", strip=True)
                    for cell in rows[1].find_all(["th", "td"])
                ]
                for index, header in enumerate(headers):
                    if index >= len(values):
                        continue
                    if header in {"course unit code", "course code"}:
                        data["course_code"] = re.sub(r"\s+", "", values[index])
                    elif header in {"course unit title", "course title"}:
                        data["course_title"] = values[index]

        for cell in soup.find_all(["td", "th", "h1", "h2", "span"]):
            text = cell.get_text(" ", strip=True)
            if not data["course_code"]:
                code_match = re.search(r"\b([A-Z]{3,4}\s*\d{3})\b", text)
                if code_match:
                    data["course_code"] = re.sub(r"\s+", "", code_match.group(1))

            if not data["course_title"] and any(
                label in text.casefold()
                for label in ("course unit title", "course title", "dersin adı")
            ):
                next_sibling = cell.find_next_sibling(["td", "th"])
                if next_sibling:
                    data["course_title"] = next_sibling.get_text(" ", strip=True)

        if not data["course_title"] and soup.title:
            data["course_title"] = soup.title.get_text(" ", strip=True)

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [
                cell.get_text(" ", strip=True).casefold()
                for cell in rows[0].find_all(["th", "td"])
            ]
            outcome_index = next(
                (
                    index
                    for index, heading in enumerate(headers)
                    if "learning outcome" in heading or "öğrenme çıkt" in heading
                ),
                None,
            )
            if outcome_index is None:
                continue

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                outcome_cell = next(
                    (
                        cell
                        for cell in cells
                        if "learning outcome"
                        in cell.get("data-label", "").casefold()
                        or "öğrenme çıkt"
                        in cell.get("data-label", "").casefold()
                    ),
                    None,
                )
                if outcome_cell:
                    candidates = [outcome_cell]
                elif outcome_index < len(cells):
                    candidates = [cells[outcome_index]]
                else:
                    candidates = cells
                for cell in candidates:
                    text = cell.get_text(" ", strip=True)
                    clean_text = re.sub(r"^\d+[\.\)]\s*", "", text)
                    if (
                        clean_text
                        and not clean_text.isdigit()
                        and clean_text.casefold() not in {"total", "toplam"}
                        and clean_text not in data["learning_outcomes"]
                    ):
                        data["learning_outcomes"].append(clean_text)

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headings = [
                cell.get_text(" ", strip=True).casefold()
                for cell in rows[0].find_all(["th", "td"])
            ]
            heading_text = " ".join(headings)
            heading_set = set(headings)
            table_id = (table.get("id") or "").casefold()
            is_assessment_table = (
                table_id == "grd_degerlendirme"
                or any(
                    label in heading_text
                    for label in (
                        "assessment components",
                        "assessment criteria",
                        "in-term studies",
                        "değerlendirme kriterleri",
                        "değerlendirme ölçütleri",
                        "contribution",
                    )
                )
                or (
                    "çalışma" in heading_set
                    and any(
                        heading in {"sayısı", "sayı", "quantity"}
                        for heading in heading_set
                    )
                    and any(
                        "katkı" in heading
                        or "contribution" in heading
                        or "percentage" in heading
                        for heading in heading_set
                    )
                )
            )
            if not is_assessment_table:
                continue

            name_index = next(
                (
                    index
                    for index, heading in enumerate(headings)
                    if heading in {"assessment components", "in-term studies", "çalışma"}
                ),
                0,
            )
            weight_index = next(
                (
                    index
                    for index, heading in enumerate(headings)
                    if any(
                        word in heading
                        for word in ("weight", "percentage", "katkı", "contribution")
                    )
                ),
                len(headings) - 1,
            )
            quantity_index = next(
                (
                    index
                    for index, heading in enumerate(headings)
                    if heading in {"quantity", "sayı", "sayısı"}
                ),
                None,
            )

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                name_cell = next(
                    (
                        cell
                        for cell in cells
                        if cell.get("data-label", "").casefold() == "çalışma"
                    ),
                    cells[name_index] if name_index < len(cells) else cells[0],
                )
                name = name_cell.get_text(" ", strip=True)
                if not name or name.casefold() in {"total", "toplam"}:
                    continue

                contribution_cell = next(
                    (
                        cell
                        for cell in cells
                        if cell.get("data-label", "").casefold().startswith(
                            ("katkı", "contribution")
                        )
                    ),
                    cells[weight_index] if weight_index < len(cells) else cells[-1],
                )
                contribution_text = contribution_cell.get_text(" ", strip=True)
                weight_match = re.search(
                    r"(\d+(?:[\.,]\d+)?)", contribution_text
                )
                if not weight_match:
                    continue

                weight = float(weight_match.group(1).replace(",", "."))
                if not 0 <= weight <= 100:
                    continue

                assessment = {"name": name, "weight": weight}
                if quantity_index is not None:
                    quantity_cell = next(
                        (
                            cell
                            for cell in cells
                            if cell.get("data-label", "").casefold()
                            in {"sayısı", "sayı"}
                        ),
                        cells[quantity_index] if quantity_index < len(cells) else None,
                    )
                    if quantity_cell:
                        quantity_match = re.search(
                            r"\d+", quantity_cell.get_text(" ", strip=True)
                        )
                        if quantity_match:
                            assessment["quantity"] = int(quantity_match.group())
                data["assessments"].append(assessment)

        return {"success": True, "error": None, "data": data}

    @staticmethod
    def sync_to_database(scraped_data: dict, user=None):
        """Save one or more scraped courses into Django models atomically."""
        if not scraped_data.get("success"):
            raise ValueError("Cannot sync unsuccessful or empty scraped course data.")

        batch = "courses" in scraped_data
        courses_data = (
            scraped_data.get("courses", [])
            if batch
            else [scraped_data.get("data")]
        )
        if not courses_data or any(not course_data for course_data in courses_data):
            raise ValueError("Cannot sync empty scraped course data.")

        synced_courses = []
        with transaction.atomic():
            for data in courses_data:
                code = data.get("course_code")
                title = data.get("course_title")
                if not code or not title:
                    raise ValueError(
                        "Every scraped course must include a code and title."
                    )

                course_defaults = {"title": title}
                if user is not None:
                    course_defaults["instructor"] = user
                course, _ = Course.objects.update_or_create(
                    code=code,
                    defaults=course_defaults,
                )

                for idx, lo_desc in enumerate(
                    data.get("learning_outcomes", []), start=1
                ):
                    LearningOutcome.objects.update_or_create(
                        course=course,
                        code=f"LO{idx}",
                        defaults={"description": lo_desc},
                    )

                for assessment in data.get("assessments", []):
                    Assessment.objects.update_or_create(
                        course=course,
                        name=assessment["name"],
                        defaults={"weight": assessment["weight"]},
                    )
                synced_courses.append(course)

        return synced_courses if batch else synced_courses[0]
