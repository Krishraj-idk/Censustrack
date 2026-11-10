"""
CensusTrack
Relational Census Enumeration & Household Survey Dashboard

Run:
    python censustrack.py

The SQLite database (censustrack.db) is created beside this script.
Only Python's standard library is required.
"""

# 1. Imports and configuration
import re
import math
import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import ttk, messagebox

APP_NAME = "CensusTrack"
APP_SUBTITLE = "Relational Census Enumeration & Household Survey Management"
DB_PATH = Path(__file__).resolve().with_name("censustrack.db")

NAVY = "#142D4E"
NAVY_DARK = "#0D2038"
TEAL = "#138A8A"
TEAL_DARK = "#0D7070"
BG = "#F3F6F8"
PANEL = "#FFFFFF"
TEXT = "#243447"
MUTED = "#667789"
BORDER = "#DCE4EA"
STRIPE = "#F7FAFC"
DANGER = "#B94747"
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 21, "bold")


# 2. Database connection
def get_connection():
    """Return a configured SQLite connection with foreign keys enabled."""
    connection = sqlite3.connect(DB_PATH, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        if enabled != 1:
            raise sqlite3.DatabaseError("SQLite foreign-key enforcement could not be enabled.")
        return connection
    except Exception:
        connection.close()
        raise


@contextmanager
def database_connection():
    """Yield a configured connection and always close it, even after errors."""
    connection = get_connection()
    try:
        yield connection
    finally:
        connection.close()


# 3. Database initialization
def initialize_database():
    """Create the relational schema if it does not already exist."""
    with database_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS survey_districts (
                district_id INTEGER PRIMARY KEY AUTOINCREMENT,
                district_name TEXT NOT NULL UNIQUE,
                contact_email TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS enumeration_blocks (
                block_id INTEGER PRIMARY KEY AUTOINCREMENT,
                district_id INTEGER NOT NULL,
                block_identifier TEXT NOT NULL,
                enumeration_date TEXT NOT NULL,
                FOREIGN KEY (district_id)
                    REFERENCES survey_districts(district_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS household_records (
                record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id INTEGER NOT NULL,
                record_type TEXT NOT NULL,
                recorded_value REAL NOT NULL,
                FOREIGN KEY (block_id)
                    REFERENCES enumeration_blocks(block_id)
                    ON DELETE CASCADE
            );
            """
        )


# 4. Database seeding
def verify_database_integrity():
    """Raise DatabaseError if SQLite reports corruption or broken foreign keys."""
    with database_connection() as connection:
        integrity_result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()

    if integrity_result != "ok":
        raise sqlite3.DatabaseError(
            f"SQLite integrity_check failed: {integrity_result}"
        )
    if foreign_key_issues:
        details = "; ".join(str(tuple(row)) for row in foreign_key_issues[:10])
        raise sqlite3.DatabaseError(
            f"Foreign-key violations detected: {details}"
        )
    return True


def seed_database_if_empty():
    """Insert one coherent sample dataset only when all three tables are empty."""
    with database_connection() as connection:
        with connection:
            # Reserve the write lock before checking emptiness so two app launches
            # cannot both seed the same initially-empty database.
            connection.execute("BEGIN IMMEDIATE")
            counts = [
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("survey_districts", "enumeration_blocks", "household_records")
            ]
            if any(counts):
                return

            cursor = connection.cursor()
            districts = [
                ("Central Ward", "central.officer@census.gov.in"),
                ("North District", "north.officer@census.gov.in"),
                ("Riverside District", "riverside.officer@census.gov.in"),
            ]
            district_ids = {}
            for name, email in districts:
                cursor.execute(
                    "INSERT INTO survey_districts (district_name, contact_email) VALUES (?, ?)",
                    (name, email),
                )
                district_ids[name] = cursor.lastrowid

            blocks = [
                (district_ids["Central Ward"], "CW-001", "2026-10-15"),
                (district_ids["Central Ward"], "CW-002", "2026-10-16"),
                (district_ids["North District"], "ND-001", "2026-10-17"),
                (district_ids["Riverside District"], "RD-001", "2026-10-18"),
            ]
            block_ids = {}
            for district_id, identifier, enumerated_on in blocks:
                cursor.execute(
                    """
                    INSERT INTO enumeration_blocks
                        (district_id, block_identifier, enumeration_date)
                    VALUES (?, ?, ?)
                    """,
                    (district_id, identifier, enumerated_on),
                )
                block_ids[identifier] = cursor.lastrowid

            records = [
                (block_ids["CW-001"], "Households Enumerated", 42),
                (block_ids["CW-001"], "Population Count", 186),
                (block_ids["CW-002"], "Households Enumerated", 37),
                (block_ids["ND-001"], "Population Count", 214),
                (block_ids["RD-001"], "Households Enumerated", 51),
            ]
            cursor.executemany(
                """
                INSERT INTO household_records (block_id, record_type, recorded_value)
                VALUES (?, ?, ?)
                """,
                records,
            )


# 5. CRUD functions
def add_census_entry(district_name, contact_email, block_identifier, record_type, recorded_value):
    """Atomically reuse/create a district, create a block, and add its record."""
    # Enforce the same rules for direct function calls as for GUI submissions.
    recorded_value = validate_entry(
        district_name, contact_email, block_identifier, record_type, str(recorded_value)
    )
    district_name = district_name.strip()
    contact_email = contact_email.strip()
    block_identifier = block_identifier.strip()
    record_type = record_type.strip()

    with database_connection() as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.cursor()
            existing = cursor.execute(
                "SELECT district_id FROM survey_districts WHERE district_name = ? COLLATE NOCASE",
                (district_name,),
            ).fetchone()

            if existing:
                district_id = existing["district_id"]
                # Keep the existing district profile; do not silently overwrite its email.
            else:
                cursor.execute(
                    """
                    INSERT INTO survey_districts (district_name, contact_email)
                    VALUES (?, ?)
                    """,
                    (district_name, contact_email),
                )
                district_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO enumeration_blocks
                    (district_id, block_identifier, enumeration_date)
                VALUES (?, ?, ?)
                """,
                (district_id, block_identifier, date.today().isoformat()),
            )
            block_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO household_records (block_id, record_type, recorded_value)
                VALUES (?, ?, ?)
                """,
                (block_id, record_type, recorded_value),
            )
            record_id = cursor.lastrowid
            return district_id, block_id, record_id


def delete_district(district_id):
    with database_connection() as connection:
        with connection:
            connection.execute(
                "DELETE FROM survey_districts WHERE district_id = ?", (district_id,)
            )


def delete_block(block_id):
    with database_connection() as connection:
        with connection:
            connection.execute(
                "DELETE FROM enumeration_blocks WHERE block_id = ?", (block_id,)
            )


def delete_record(record_id):
    with database_connection() as connection:
        with connection:
            connection.execute(
                "DELETE FROM household_records WHERE record_id = ?", (record_id,)
            )


# 6. Input validation
EMAIL_LOCAL_PATTERN = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$"
)
EMAIL_DOMAIN_LABEL_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def validate_entry(district_name, email, block_identifier, record_type, value_text):
    if not district_name.strip():
        raise ValueError("Enter a district name.")
    if not email.strip():
        raise ValueError("Enter the district officer's email address.")
    email = email.strip()
    if len(email) > 254 or email.count("@") != 1:
        raise ValueError("Enter a valid email address, for example officer@example.gov.in.")
    local_part, domain = email.split("@")
    domain_labels = domain.split(".")
    if (
        not local_part
        or len(local_part) > 64
        or not EMAIL_LOCAL_PATTERN.fullmatch(local_part)
        or len(domain) > 253
        or len(domain_labels) < 2
        or any(
            not label
            or len(label) > 63
            or not EMAIL_DOMAIN_LABEL_PATTERN.fullmatch(label)
            for label in domain_labels
        )
    ):
        raise ValueError("Enter a valid email address, for example officer@example.gov.in.")
    if not block_identifier.strip():
        raise ValueError("Enter a block identifier.")
    if not record_type.strip():
        raise ValueError("Enter a record type.")
    if not value_text.strip():
        raise ValueError("Enter a recorded value.")

    try:
        decimal_value = Decimal(value_text.strip())
    except (InvalidOperation, ValueError):
        raise ValueError("Recorded value must be a number (integer or decimal).")

    if not decimal_value.is_finite():
        raise ValueError("Recorded value must be finite; NaN and infinity are not allowed.")
    if decimal_value < 0:
        raise ValueError("Recorded value cannot be negative.")

    try:
        value = float(decimal_value)
    except (OverflowError, ValueError):
        raise ValueError("Recorded value is too large for SQLite's REAL numeric range.")

    if not math.isfinite(value):
        raise ValueError("Recorded value is too large; enter a smaller finite number.")
    if decimal_value != 0 and value == 0.0:
        raise ValueError("Recorded value is too small to store accurately; enter a larger value.")
    return value


# 7–8. Table and dropdown refresh functions
class CensusTrackApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} | Census Management")
        self.root.geometry("1240x790")
        self.root.minsize(980, 650)
        self.root.configure(bg=BG)

        self.district_options = {}
        self.block_options = {}
        self.record_options = {}

        self._configure_style()
        self._build_interface()
        self.refresh_all()

    def _configure_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=FONT)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=FONT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT, font=FONT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", background=NAVY, foreground="white", font=FONT_TITLE)
        style.configure("Subtitle.TLabel", background=NAVY, foreground="#D7E4EF", font=("Segoe UI", 10))
        style.configure("Section.TLabel", background=PANEL, foreground=NAVY, font=("Segoe UI", 12, "bold"))
        style.configure("TButton", padding=(10, 7), font=("Segoe UI", 9, "bold"))
        style.configure("Primary.TButton", background=TEAL, foreground="white", borderwidth=0)
        style.map("Primary.TButton", background=[("active", TEAL_DARK), ("disabled", "#9BB9B9")])
        style.configure("Danger.TButton", background=DANGER, foreground="white", borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#963939")])
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=5)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(15, 9), font=FONT_BOLD)
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", NAVY)])
        style.configure(
            "Treeview",
            background="white",
            fieldbackground="white",
            foreground=TEXT,
            rowheight=27,
            bordercolor=BORDER,
            borderwidth=1,
            font=("Segoe UI", 9),
        )
        style.configure("Treeview.Heading", background="#E8EFF4", foreground=NAVY, font=FONT_BOLD, padding=7)
        style.map("Treeview", background=[("selected", "#D6EEEE")], foreground=[("selected", NAVY)])

    # 9. GUI construction
    def _build_interface(self):
        """Build the responsive administrative dashboard."""
        self.root.title(f"{APP_NAME} | Census Management")
        self.root.geometry("1320x850")
        self.root.minsize(1000, 680)
        self.root.configure(bg=BG)

        header = tk.Frame(self.root, bg=NAVY, height=88)
        header.pack(fill="x")
        header.pack_propagate(False)

        brand = tk.Frame(header, bg=NAVY)
        brand.pack(side="left", padx=24, pady=13)
        tk.Label(
            brand, text=APP_NAME, bg=NAVY, fg="white",
            font=("Segoe UI", 22, "bold")
        ).pack(anchor="w")
        tk.Label(
            brand, text="Census Enumeration & Household Survey Management",
            bg=NAVY, fg="#D5E2ED", font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(1, 0))

        header_right = tk.Frame(header, bg=NAVY)
        header_right.pack(side="right", padx=24, pady=16)
        self.header_date = tk.Label(
            header_right, text=date.today().strftime("%A, %d %B %Y"),
            bg=NAVY, fg="#D5E2ED", font=("Segoe UI", 9)
        )
        self.header_date.pack(anchor="e")
        self.status_label = tk.Label(
            header_right, text="●  DATABASE CONNECTED",
            bg=NAVY, fg="#9FE2D5", font=("Segoe UI", 9, "bold")
        )
        self.status_label.pack(anchor="e", pady=(7, 0))

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=16)

        self._build_summary_cards(main)

        workspace = tk.Frame(main, bg=BG)
        workspace.pack(fill="both", expand=True, pady=(15, 0))
        workspace.grid_columnconfigure(0, weight=0, minsize=350)
        workspace.grid_columnconfigure(1, weight=1)
        workspace.grid_rowconfigure(0, weight=1)

        self._build_left_panel(workspace)
        self._build_display_panel(workspace)

        footer = tk.Frame(self.root, bg="#E8EEF2", height=28)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        tk.Label(
            footer,
            text=f"  SQLite database: {DB_PATH.name}   •   Foreign-key enforcement enabled",
            bg="#E8EEF2", fg=MUTED, font=("Segoe UI", 8)
        ).pack(side="left", pady=5)

    def _build_summary_cards(self, parent):
        cards = tk.Frame(parent, bg=BG)
        cards.pack(fill="x")
        self.summary_values = {}

        definitions = [
            ("districts", "TOTAL SURVEY DISTRICTS", "▦", TEAL),
            ("blocks", "TOTAL ENUMERATION BLOCKS", "▤", "#3976A8"),
            ("records", "TOTAL HOUSEHOLD RECORDS", "▧", "#6C7FA6"),
            ("database", "DATABASE STATUS", "●", "#27845D"),
        ]

        for index, (key, label, symbol, accent) in enumerate(definitions):
            cards.grid_columnconfigure(index, weight=1, uniform="summary")
            card = tk.Frame(
                cards, bg=PANEL, highlightbackground=BORDER, highlightthickness=1
            )
            card.grid(
                row=0, column=index, sticky="nsew",
                padx=(0 if index == 0 else 9, 0)
            )
            accent_bar = tk.Frame(card, bg=accent, width=4)
            accent_bar.pack(side="left", fill="y")
            content = tk.Frame(card, bg=PANEL)
            content.pack(side="left", fill="both", expand=True, padx=12, pady=9)
            top = tk.Frame(content, bg=PANEL)
            top.pack(fill="x")
            tk.Label(
                top, text=label, bg=PANEL, fg=MUTED,
                font=("Segoe UI", 8, "bold")
            ).pack(side="left", anchor="w")
            tk.Label(
                top, text=symbol, bg=PANEL, fg=accent,
                font=("Segoe UI", 13, "bold")
            ).pack(side="right")
            value = tk.Label(
                content, text="—", bg=PANEL, fg=NAVY,
                font=("Segoe UI", 20, "bold")
            )
            value.pack(anchor="w", pady=(2, 0))
            self.summary_values[key] = value

    def _build_left_panel(self, parent):
        """Place data-entry and deletion workflows in separate compact tabs."""
        panel = tk.Frame(
            parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1
        )
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        tk.Label(
            panel, text="DATA MANAGEMENT", bg=PANEL, fg=NAVY,
            font=("Segoe UI", 11, "bold")
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(13, 8))

        self.action_notebook = ttk.Notebook(panel)
        self.action_notebook.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=(0, 10)
        )

        insert_tab = tk.Frame(self.action_notebook, bg=PANEL, padx=14, pady=12)
        delete_tab = tk.Frame(self.action_notebook, bg=PANEL, padx=14, pady=12)
        self.action_notebook.add(insert_tab, text="  Add Record  ")
        self.action_notebook.add(delete_tab, text="  Delete Data  ")

        for column in range(1):
            insert_tab.grid_columnconfigure(column, weight=1)

        tk.Label(
            insert_tab, text="Create a census entry", bg=PANEL, fg=NAVY,
            font=("Segoe UI", 12, "bold")
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            insert_tab,
            text="A submission creates an enumeration block and its household record.",
            bg=PANEL, fg=MUTED, wraplength=285, justify="left",
            font=("Segoe UI", 8)
        ).grid(row=1, column=0, sticky="w", pady=(3, 12))

        self.district_var = tk.StringVar()
        self.email_var = tk.StringVar()
        self.block_var = tk.StringVar()
        self.record_type_var = tk.StringVar()
        self.value_var = tk.StringVar()
        self.form_entries = []

        fields = [
            ("District Name", self.district_var, "e.g. Central Ward"),
            ("District Officer Email", self.email_var, "officer@example.gov.in"),
            ("Block Identifier", self.block_var, "e.g. CW-003"),
            ("Record Type", self.record_type_var, "e.g. Population Count"),
            ("Recorded Value", self.value_var, "Enter a non-negative number"),
        ]
        for index, (label, variable, placeholder) in enumerate(fields):
            label_row = 2 + index * 2
            tk.Label(
                insert_tab, text=f"{label}  *", bg=PANEL, fg=TEXT,
                font=("Segoe UI", 9, "bold")
            ).grid(row=label_row, column=0, sticky="w", pady=(5, 3))
            entry = ttk.Entry(insert_tab, textvariable=variable)
            entry.grid(row=label_row + 1, column=0, sticky="ew", ipady=4)
            self.form_entries.append((entry, variable, placeholder))
            self._add_placeholder(entry, variable, placeholder)

        tk.Label(
            insert_tab, text="* Required fields", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 8)
        ).grid(row=12, column=0, sticky="w", pady=(8, 8))

        action_row = tk.Frame(insert_tab, bg=PANEL)
        action_row.grid(row=13, column=0, sticky="ew")
        action_row.grid_columnconfigure(0, weight=1)
        action_row.grid_columnconfigure(1, weight=1)
        ttk.Button(
            action_row, text="Add Record", style="Primary.TButton",
            command=self.handle_insert
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(
            action_row, text="Clear Form", command=self.clear_form
        ).grid(row=0, column=1, sticky="ew", padx=(5, 0))

        tk.Label(
            delete_tab, text="Remove database entries", bg=PANEL, fg=NAVY,
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w")
        tk.Label(
            delete_tab,
            text="Choose an item below. Parent deletions also remove dependent records.",
            bg=PANEL, fg=MUTED, wraplength=285, justify="left",
            font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(3, 10))

        self.district_delete_var = tk.StringVar()
        self.block_delete_var = tk.StringVar()
        self.record_delete_var = tk.StringVar()

        self._build_delete_card(
            delete_tab, "01  Survey District", self.district_delete_var,
            "district_combo", "Delete District", self.handle_delete_district,
            "Cascades to all blocks and their records"
        )
        self._build_delete_card(
            delete_tab, "02  Enumeration Block", self.block_delete_var,
            "block_combo", "Delete Block", self.handle_delete_block,
            "Cascades to household records in this block"
        )
        self._build_delete_card(
            delete_tab, "03  Household Record", self.record_delete_var,
            "record_combo", "Delete Record", self.handle_delete_record,
            "Removes only the selected record"
        )

    @staticmethod
    def _add_placeholder(entry, variable, placeholder):
        """Add a subtle placeholder that is not submitted as actual field data."""
        placeholder_color = "#8795A3"
        normal_color = TEXT
        variable.set(placeholder)
        entry.configure(foreground=placeholder_color)

        def on_focus_in(_event):
            if variable.get() == placeholder:
                variable.set("")
                entry.configure(foreground=normal_color)

        def on_focus_out(_event):
            if not variable.get().strip():
                variable.set(placeholder)
                entry.configure(foreground=placeholder_color)

        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

    def clear_form(self):
        """Reset all inputs and restore their visual placeholder text."""
        for entry, variable, placeholder in self.form_entries:
            variable.set(placeholder)
            entry.configure(foreground="#8795A3")
        self.root.focus_set()

    def _build_delete_card(self, parent, title, variable, attr_name,
                           button_text, callback, description):
        card = tk.Frame(
            parent, bg="#F8FAFC", highlightbackground=BORDER, highlightthickness=1
        )
        card.pack(fill="x", pady=(0, 9))
        tk.Label(
            card, text=title, bg="#F8FAFC", fg=NAVY,
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", padx=9, pady=(7, 1))
        tk.Label(
            card, text=description, bg="#F8FAFC", fg=MUTED,
            font=("Segoe UI", 7), wraplength=275, justify="left"
        ).pack(anchor="w", padx=9, pady=(0, 5))
        combo = ttk.Combobox(card, textvariable=variable, state="readonly")
        combo.pack(fill="x", padx=9, pady=(0, 6))
        setattr(self, attr_name, combo)
        ttk.Button(
            card, text=button_text, style="Danger.TButton", command=callback
        ).pack(fill="x", padx=9, pady=(0, 8))

    def _build_display_panel(self, parent):
        panel = tk.Frame(
            parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1
        )
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        top = tk.Frame(panel, bg=PANEL)
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(13, 10))
        tk.Label(
            top, text="Census Database", bg=PANEL, fg=NAVY,
            font=("Segoe UI", 12, "bold")
        ).pack(side="left")
        ttk.Button(
            top, text="↻  Refresh Data", command=self.refresh_all
        ).pack(side="right")

        self.notebook = ttk.Notebook(panel)
        self.notebook.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=(0, 10)
        )

        self.tree_specs = {
            "combined": (
                "Combined Census Records",
                ("block_id", "district_name", "block_identifier", "enumeration_date", "record_type", "recorded_value"),
                ("Block ID", "District Name", "Block Identifier", "Enumeration Date", "Record Type", "Recorded Value"),
                (75, 145, 125, 115, 155, 100),
            ),
            "districts": (
                "Survey Districts",
                ("district_id", "district_name", "contact_email"),
                ("District ID", "District Name", "Contact Email"),
                (85, 180, 230),
            ),
            "blocks": (
                "Enumeration Blocks",
                ("block_id", "district_id", "block_identifier", "enumeration_date"),
                ("Block ID", "District ID", "Block Identifier", "Enumeration Date"),
                (85, 90, 160, 140),
            ),
            "records": (
                "Household Records",
                ("record_id", "block_id", "record_type", "recorded_value"),
                ("Record ID", "Block ID", "Record Type", "Recorded Value"),
                (85, 85, 190, 120),
            ),
        }
        self.trees = {}
        for key, (tab_name, columns, headings, widths) in self.tree_specs.items():
            tab = tk.Frame(self.notebook, bg=PANEL, padx=7, pady=7)
            self.notebook.add(tab, text=f"  {tab_name}  ")
            tab.grid_rowconfigure(0, weight=1)
            tab.grid_columnconfigure(0, weight=1)

            tree = ttk.Treeview(
                tab, columns=columns, show="headings", selectmode="browse"
            )
            for column, heading, width in zip(columns, headings, widths):
                tree.heading(column, text=heading)
                numeric = column in ("block_id", "district_id", "record_id", "recorded_value")
                tree.column(
                    column, width=width, minwidth=65,
                    anchor="center" if numeric else "w", stretch=True
                )

            vertical = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
            horizontal = ttk.Scrollbar(tab, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
            tree.grid(row=0, column=0, sticky="nsew")
            vertical.grid(row=0, column=1, sticky="ns")
            horizontal.grid(row=1, column=0, sticky="ew")
            tree.tag_configure("even", background="#FFFFFF")
            tree.tag_configure("odd", background="#F3F7FA")
            tree.tag_configure("empty", foreground="#8795A3", background="#FFFFFF")
            self.trees[key] = tree

        # The joined, three-table view is the default landing tab.
        self.notebook.select(0)

    # 10. Event handlers
    def handle_insert(self):
        try:
            submitted = [
                self.district_var.get(),
                self.email_var.get(),
                self.block_var.get(),
                self.record_type_var.get(),
                self.value_var.get(),
            ]
            placeholders = {
                "e.g. Central Ward", "officer@example.gov.in", "e.g. CW-003",
                "e.g. Population Count", "Enter a non-negative number"
            }
            submitted = ["" if item in placeholders else item for item in submitted]
            value = validate_entry(*submitted)
            district_id, block_id, record_id = add_census_entry(
                submitted[0].strip(),
                submitted[1].strip(),
                submitted[2].strip(),
                submitted[3].strip(),
                value,
            )
        except ValueError as error:
            messagebox.showerror("Input Validation", str(error), parent=self.root)
            return
        except sqlite3.IntegrityError as error:
            messagebox.showerror(
                "Database Constraint", f"The entry could not be saved.\n\n{error}",
                parent=self.root
            )
            return
        except sqlite3.Error as error:
            messagebox.showerror(
                "Database Error", f"The transaction was rolled back.\n\n{error}",
                parent=self.root
            )
            return

        self.clear_form()
        self.refresh_all()
        messagebox.showinfo(
            "Entry Saved",
            f"Census entry added successfully.\n\nDistrict ID: {district_id}\n"
            f"Block ID: {block_id}\nRecord ID: {record_id}",
            parent=self.root,
        )

    def _selected_id(self, variable, mapping, kind):
        selected = variable.get()
        if not selected or selected not in mapping:
            messagebox.showwarning(
                "Selection Required", f"Select a valid {kind} from the dropdown.",
                parent=self.root
            )
            return None
        return mapping[selected]

    def handle_delete_district(self):
        district_id = self._selected_id(self.district_delete_var, self.district_options, "district")
        if district_id is None:
            return
        label = self.district_delete_var.get()
        if not messagebox.askyesno(
            "Confirm Cascading Deletion",
            f"Delete {label}?\n\nThis permanently deletes the district, all its "
            "enumeration blocks, and every household record within those blocks.",
            icon="warning", parent=self.root
        ):
            return
        self._perform_delete(delete_district, district_id, "Survey district")

    def handle_delete_block(self):
        block_id = self._selected_id(self.block_delete_var, self.block_options, "block")
        if block_id is None:
            return
        label = self.block_delete_var.get()
        if not messagebox.askyesno(
            "Confirm Deletion",
            f"Delete {label}?\n\nAll household records belonging to this block will also be deleted.",
            icon="warning", parent=self.root
        ):
            return
        self._perform_delete(delete_block, block_id, "Enumeration block")

    def handle_delete_record(self):
        record_id = self._selected_id(self.record_delete_var, self.record_options, "record")
        if record_id is None:
            return
        label = self.record_delete_var.get()
        if not messagebox.askyesno(
            "Confirm Deletion", f"Delete {label}?\n\nOnly this household record will be deleted.",
            icon="warning", parent=self.root
        ):
            return
        self._perform_delete(delete_record, record_id, "Household record")

    def _perform_delete(self, delete_function, item_id, item_name):
        try:
            delete_function(item_id)
        except sqlite3.Error as error:
            messagebox.showerror(
                "Database Error", f"{item_name} could not be deleted.\n\n{error}",
                parent=self.root
            )
            return
        self.refresh_all()
        messagebox.showinfo("Deletion Complete", f"{item_name} deleted successfully.", parent=self.root)

    # 7–8. Central refresh and dropdown refresh
    def refresh_all(self):
        """Refresh every table, summary card, and deletion selector from SQLite."""
        try:
            with database_connection() as connection:
                combined_rows = connection.execute(
                    """
                    SELECT b.block_id, d.district_name, b.block_identifier,
                           b.enumeration_date, h.record_type, h.recorded_value
                    FROM survey_districts AS d
                    INNER JOIN enumeration_blocks AS b ON b.district_id = d.district_id
                    INNER JOIN household_records AS h ON h.block_id = b.block_id
                    ORDER BY d.district_name, b.block_id, h.record_id
                    """
                ).fetchall()
                district_rows = connection.execute(
                    "SELECT district_id, district_name, contact_email FROM survey_districts ORDER BY district_id"
                ).fetchall()
                block_rows = connection.execute(
                    """
                    SELECT block_id, district_id, block_identifier, enumeration_date
                    FROM enumeration_blocks ORDER BY block_id
                    """
                ).fetchall()
                record_rows = connection.execute(
                    """
                    SELECT record_id, block_id, record_type, recorded_value
                    FROM household_records ORDER BY record_id
                    """
                ).fetchall()
                counts = {
                    "districts": connection.execute("SELECT COUNT(*) FROM survey_districts").fetchone()[0],
                    "blocks": connection.execute("SELECT COUNT(*) FROM enumeration_blocks").fetchone()[0],
                    "records": connection.execute("SELECT COUNT(*) FROM household_records").fetchone()[0],
                }
                block_labels = connection.execute(
                    """
                    SELECT b.block_id, b.block_identifier, d.district_name
                    FROM enumeration_blocks b
                    JOIN survey_districts d ON d.district_id = b.district_id
                    ORDER BY b.block_id
                    """
                ).fetchall()
                record_labels = connection.execute(
                    """
                    SELECT h.record_id, h.block_id, h.record_type
                    FROM household_records h ORDER BY h.record_id
                    """
                ).fetchall()
        except sqlite3.Error as error:
            self.status_label.config(text="DATABASE ERROR", fg="#FFB3B3")
            messagebox.showerror("Database Error", str(error), parent=self.root)
            return

        self._populate_tree(self.trees["combined"], combined_rows, self.tree_specs["combined"][1])
        self._populate_tree(self.trees["districts"], district_rows, self.tree_specs["districts"][1])
        self._populate_tree(self.trees["blocks"], block_rows, self.tree_specs["blocks"][1])
        self._populate_tree(self.trees["records"], record_rows, self.tree_specs["records"][1])

        for key, count in counts.items():
            self.summary_values[key].config(text=f"{count:,}")
        self.summary_values["database"].config(text="ONLINE", fg="#27845D")

        self.district_options = {
            f"#{row['district_id']}  |  {row['district_name']}": row["district_id"]
            for row in district_rows
        }
        self.block_options = {
            f"#{row['block_id']}  |  {row['block_identifier']}  |  {row['district_name']}": row["block_id"]
            for row in block_labels
        }
        self.record_options = {
            f"#{row['record_id']}  |  Block {row['block_id']}  |  {row['record_type']}": row["record_id"]
            for row in record_labels
        }
        self._set_combo_values(self.district_combo, self.district_delete_var, self.district_options)
        self._set_combo_values(self.block_combo, self.block_delete_var, self.block_options)
        self._set_combo_values(self.record_combo, self.record_delete_var, self.record_options)
        self.status_label.config(text="DATABASE CONNECTED", fg="#9FE2D5")

    @staticmethod
    def _populate_tree(tree, rows, columns):
        tree.delete(*tree.get_children())
        if not rows:
            tree.insert("", "end", values=tuple("No records available" if i == 0 else "—"
                                               for i, _ in enumerate(columns)), tags=("empty",))
            return
        for index, row in enumerate(rows):
            values = []
            for column in columns:
                value = row[column]
                if column == "recorded_value" and isinstance(value, (int, float)):
                    value = f"{value:g}"
                values.append(value)
            tree.insert("", "end", values=values, tags=("even" if index % 2 == 0 else "odd",))

    @staticmethod
    def _set_combo_values(combo, variable, mapping):
        valid_values = list(mapping.keys())
        current = variable.get()
        combo["values"] = valid_values
        if current not in mapping:
            variable.set("")


# 11. Application initialization
def main():
    initialize_database()
    seed_database_if_empty()

    verify_database_integrity()

    root = tk.Tk()
    CensusTrackApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()