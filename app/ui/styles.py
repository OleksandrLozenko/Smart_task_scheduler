from __future__ import annotations


def _theme_tokens(theme_name: str) -> dict[str, str]:
    themes: dict[str, dict[str, str]] = {
        "ocean": {
            "bg_from": "#2B4D63",
            "bg_to": "#233746",
            "title_bar": "rgba(18, 34, 49, 0.62)",
            "text_main": "#EAF5FF",
            "text_soft": "#CFE2F2",
            "sidebar_bg": "rgba(18, 45, 63, 0.42)",
            "sidebar_border": "rgba(220, 243, 255, 0.22)",
            "card_rgb": "58, 102, 133",
            "card_border": "rgba(220, 243, 255, 0.26)",
            "mode_checked": "rgba(8, 21, 32, 0.35)",
            "mode_hover": "rgba(255, 255, 255, 0.10)",
            "shell_bg": "rgba(255, 255, 255, 0.04)",
            "shell_border": "rgba(226, 244, 255, 0.16)",
            "primary_bg": "#F2F7FB",
            "primary_fg": "#2D5C7B",
            "secondary_bg": "rgba(255, 255, 255, 0.16)",
            "secondary_border": "rgba(255, 255, 255, 0.22)",
            "secondary_fg": "#EAF5FF",
            "danger_bg": "rgba(215, 80, 87, 0.92)",
            "accent": "#6CC2EA",
            "window_ctrl": "#EAF5FF",
        },
        "rose": {
            "bg_from": "#BE575B",
            "bg_to": "#A9474B",
            "title_bar": "rgba(103, 34, 39, 0.52)",
            "text_main": "#FFF2F2",
            "text_soft": "#F6DDDD",
            "sidebar_bg": "rgba(120, 37, 42, 0.34)",
            "sidebar_border": "rgba(255, 230, 230, 0.24)",
            "card_rgb": "203, 107, 112",
            "card_border": "rgba(250, 220, 220, 0.24)",
            "mode_checked": "rgba(0, 0, 0, 0.18)",
            "mode_hover": "rgba(255, 255, 255, 0.12)",
            "shell_bg": "rgba(255, 255, 255, 0.04)",
            "shell_border": "rgba(255, 255, 255, 0.12)",
            "primary_bg": "#F2ECEC",
            "primary_fg": "#B25055",
            "secondary_bg": "rgba(255, 255, 255, 0.16)",
            "secondary_border": "rgba(255, 255, 255, 0.18)",
            "secondary_fg": "#FCEEEE",
            "danger_bg": "rgba(215, 72, 79, 0.92)",
            "accent": "#FF6F75",
            "window_ctrl": "#FCEEEE",
        },
        "forest": {
            "bg_from": "#3C5A4F",
            "bg_to": "#2B4037",
            "title_bar": "rgba(27, 47, 38, 0.58)",
            "text_main": "#EDF8F1",
            "text_soft": "#D6EBDD",
            "sidebar_bg": "rgba(36, 67, 52, 0.4)",
            "sidebar_border": "rgba(221, 245, 230, 0.22)",
            "card_rgb": "84, 132, 108",
            "card_border": "rgba(221, 245, 230, 0.22)",
            "mode_checked": "rgba(11, 25, 18, 0.34)",
            "mode_hover": "rgba(255, 255, 255, 0.10)",
            "shell_bg": "rgba(255, 255, 255, 0.05)",
            "shell_border": "rgba(230, 249, 237, 0.15)",
            "primary_bg": "#EDF8F1",
            "primary_fg": "#3E6C55",
            "secondary_bg": "rgba(255, 255, 255, 0.16)",
            "secondary_border": "rgba(255, 255, 255, 0.2)",
            "secondary_fg": "#EDF8F1",
            "danger_bg": "rgba(208, 89, 95, 0.9)",
            "accent": "#8ED8A8",
            "window_ctrl": "#EDF8F1",
        },
        "sunset": {
            "bg_from": "#5B3F66",
            "bg_to": "#45314F",
            "title_bar": "rgba(47, 28, 55, 0.62)",
            "text_main": "#FFF3E9",
            "text_soft": "#F6DCC6",
            "sidebar_bg": "rgba(80, 51, 88, 0.42)",
            "sidebar_border": "rgba(255, 229, 205, 0.24)",
            "card_rgb": "151, 96, 110",
            "card_border": "rgba(255, 228, 208, 0.26)",
            "mode_checked": "rgba(40, 20, 35, 0.34)",
            "mode_hover": "rgba(255, 255, 255, 0.12)",
            "shell_bg": "rgba(255, 255, 255, 0.05)",
            "shell_border": "rgba(255, 239, 224, 0.16)",
            "primary_bg": "#FFF0E5",
            "primary_fg": "#8A4F5A",
            "secondary_bg": "rgba(255, 255, 255, 0.17)",
            "secondary_border": "rgba(255, 245, 236, 0.24)",
            "secondary_fg": "#FFF6F0",
            "danger_bg": "rgba(219, 90, 97, 0.92)",
            "accent": "#FFC281",
            "window_ctrl": "#FFF6F0",
        },
        "graphite": {
            "bg_from": "#2F3640",
            "bg_to": "#242B33",
            "title_bar": "rgba(25, 31, 39, 0.68)",
            "text_main": "#ECF3FA",
            "text_soft": "#CCD8E5",
            "sidebar_bg": "rgba(36, 45, 56, 0.48)",
            "sidebar_border": "rgba(211, 226, 240, 0.20)",
            "card_rgb": "75, 96, 116",
            "card_border": "rgba(211, 226, 240, 0.24)",
            "mode_checked": "rgba(15, 20, 27, 0.42)",
            "mode_hover": "rgba(255, 255, 255, 0.10)",
            "shell_bg": "rgba(255, 255, 255, 0.05)",
            "shell_border": "rgba(211, 226, 240, 0.15)",
            "primary_bg": "#EAF1F8",
            "primary_fg": "#355D7E",
            "secondary_bg": "rgba(255, 255, 255, 0.15)",
            "secondary_border": "rgba(255, 255, 255, 0.22)",
            "secondary_fg": "#ECF3FA",
            "danger_bg": "rgba(214, 87, 95, 0.90)",
            "accent": "#88BEEA",
            "window_ctrl": "#ECF3FA",
        },
    }
    return themes.get(theme_name, themes["ocean"])


def build_app_stylesheet(
    *,
    theme_name: str = "ocean",
    main_card_opacity_percent: int = 94,
    main_start_button_height: int = 48,
    ui_scale_percent: int = 100,
) -> str:
    tokens = _theme_tokens(theme_name)
    card_alpha = int(max(72, min(100, main_card_opacity_percent)) * 255 / 100)
    start_height = max(38, min(64, main_start_button_height))
    scale = max(85, min(130, ui_scale_percent)) / 100.0

    def fs(px: int, *, min_px: int = 10) -> int:
        return max(min_px, int(round(px * scale)))

    return f"""
QMainWindow {{
    background: qlineargradient(
        x1: 0, y1: 0,
        x2: 1, y2: 1,
        stop: 0 {tokens["bg_from"]},
        stop: 1 {tokens["bg_to"]}
    );
}}

QWidget {{
    color: {tokens["text_main"]};
    font-family: "Segoe UI";
    font-size: {fs(15)}px;
}}

QToolTip {{
    background: rgba(19, 28, 39, 0.95);
    color: #F5FBFF;
    border: 1px solid rgba(176, 220, 246, 0.45);
    border-radius: 8px;
    padding: 8px 10px;
    font-size: {fs(15)}px;
    font-weight: 600;
}}

#root {{
    background: transparent;
}}

#windowTitleBar {{
    background: {tokens["title_bar"]};
    border-bottom: 1px solid rgba(255, 255, 255, 0.15);
}}

#windowTitleLabel {{
    color: {tokens["text_main"]};
    font-size: {fs(17)}px;
    font-weight: 700;
}}

QPushButton#windowCtrlButton,
QPushButton#windowCloseButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: {tokens["window_ctrl"]};
    font-size: {fs(14)}px;
    font-weight: 600;
}}

QPushButton#windowCtrlButton:hover {{
    background: rgba(255, 255, 255, 0.14);
}}

QPushButton#windowCloseButton:hover {{
    background: {tokens["danger_bg"]};
    border-color: rgba(255, 255, 255, 0.28);
}}

#sidebar {{
    background: {tokens["sidebar_bg"]};
    border: 1px solid {tokens["sidebar_border"]};
    border-radius: 14px;
}}

#sidebarTitle {{
    color: {tokens["text_main"]};
    font-size: {fs(32)}px;
    font-weight: 700;
}}

#sidebarSparkles {{
    min-width: 18px;
    min-height: 18px;
}}

#sidebarSubtitle {{
    color: {tokens["text_soft"]};
    font-size: {fs(15)}px;
    font-weight: 500;
}}

QPushButton#sidebarNavButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 12px;
    color: {tokens["text_main"]};
    font-size: {fs(17)}px;
    font-weight: 600;
    text-align: left;
    min-height: 48px;
    padding: 9px 11px;
}}

QPushButton#sidebarNavButton:hover {{
    background: {tokens["mode_hover"]};
}}

QPushButton#sidebarNavButton:checked {{
    background: {tokens["mode_checked"]};
    border-color: rgba(255, 255, 255, 0.16);
}}

QPushButton#sidebarSettingsButton {{
    background: {tokens["secondary_bg"]};
    border: 1px solid {tokens["secondary_border"]};
    border-radius: 12px;
    color: {tokens["text_main"]};
    font-size: {fs(17)}px;
    font-weight: 600;
    text-align: left;
    min-height: 48px;
    padding: 9px 11px;
}}

QPushButton#sidebarSettingsButton:hover {{
    background: rgba(255, 255, 255, 0.24);
}}

QPushButton#sidebarSettingsButton:checked {{
    background: {tokens["mode_checked"]};
    border-color: rgba(255, 255, 255, 0.16);
}}

#card {{
    background: rgba({tokens["card_rgb"]}, {card_alpha});
    border: 1px solid {tokens["card_border"]};
    border-radius: 14px;
}}

QPushButton#modeButton {{
    background: transparent;
    border: none;
    border-radius: 9px;
    color: {tokens["text_main"]};
    font-size: {fs(16)}px;
    font-weight: 500;
    min-height: 34px;
    padding: 6px 12px;
}}

QPushButton#modeButton:hover {{
    background: {tokens["mode_hover"]};
}}

QPushButton#modeButton:checked {{
    background: {tokens["mode_checked"]};
    color: white;
}}

#timerShell {{
    background: {tokens["shell_bg"]};
    border: 1px solid {tokens["shell_border"]};
    border-radius: 14px;
}}

#circularTimer {{
    background: transparent;
}}

QPushButton#timeArrowButton {{
    background: {tokens["secondary_bg"]};
    border: 1px solid {tokens["secondary_border"]};
    border-radius: 9px;
    color: {tokens["text_main"]};
    min-width: 46px;
    max-width: 46px;
    min-height: 38px;
    max-height: 38px;
    font-size: {fs(20)}px;
    font-weight: 700;
}}

QPushButton#timeArrowButton:hover {{
    background: rgba(255, 255, 255, 0.22);
}}

QPushButton#primaryButton {{
    background: {tokens["primary_bg"]};
    border: none;
    border-radius: 8px;
    color: {tokens["primary_fg"]};
    font-size: {fs(19)}px;
    font-weight: 700;
    min-height: {start_height}px;
    padding: 6px 14px;
}}

QPushButton#primaryButton:hover {{
    background: rgba(255, 255, 255, 0.92);
}}

QPushButton#secondaryButton,
QPushButton#linkButton,
QPushButton#floatingPrimary {{
    border-radius: 8px;
    font-weight: 600;
    min-height: 36px;
    padding: 8px 14px;
}}

QPushButton#secondaryButton,
QPushButton#linkButton {{
    background: {tokens["secondary_bg"]};
    border: 1px solid {tokens["secondary_border"]};
    color: {tokens["secondary_fg"]};
}}

QPushButton#secondaryButton:hover,
QPushButton#linkButton:hover {{
    background: rgba(255, 255, 255, 0.24);
}}

#cycleLabel {{
    color: {tokens["text_main"]};
    font-size: {fs(32)}px;
    font-weight: 600;
}}

#statusLabel {{
    color: {tokens["text_main"]};
    font-size: {fs(26)}px;
    font-weight: 600;
}}

#planningCard,
#settingsPageCard,
#tasksCard {{
    background: rgba({tokens["card_rgb"]}, {card_alpha});
    border: 1px solid {tokens["card_border"]};
    border-radius: 14px;
}}

#tasksTitle {{
    color: white;
    font-size: {fs(34)}px;
    font-weight: 700;
}}

#tasksHint {{
    color: {tokens["text_main"]};
    font-size: {fs(18)}px;
}}

#tasksHintSecondary {{
    color: rgba(255, 244, 244, 0.86);
    font-size: {fs(14)}px;
    font-weight: 500;
}}

#tasksScrollArea,
#tasksScrollArea QWidget {{
    background: transparent;
}}

#tasksScrollArea QScrollBar:vertical {{
    background: rgba(255, 255, 255, 0.08);
    width: 10px;
    margin: 3px 2px 3px 0;
    border-radius: 5px;
}}

#tasksScrollArea QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.30);
    min-height: 28px;
    border-radius: 5px;
}}

#tasksScrollArea QScrollBar::add-line:vertical,
#tasksScrollArea QScrollBar::sub-line:vertical {{
    height: 0px;
}}

#tasksDayCard {{
    background: rgba(0, 0, 0, 0.16);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 12px;
}}

QPushButton#tasksDayHeaderButton {{
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 8px;
    color: {tokens["text_main"]};
    font-size: {fs(16)}px;
    font-weight: 700;
    text-align: left;
    min-height: 42px;
    padding: 6px 10px;
}}

QPushButton#tasksDayHeaderButton:hover {{
    background: rgba(255, 255, 255, 0.16);
}}

#tasksDayEmptyLabel {{
    color: rgba(255, 242, 242, 0.85);
    font-size: {fs(14)}px;
    font-weight: 500;
    background: rgba(0, 0, 0, 0.12);
    border: 1px dashed rgba(255, 255, 255, 0.16);
    border-radius: 8px;
    padding: 8px 10px;
}}

#tasksDayTable {{
    background: rgba(0, 0, 0, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 10px;
    gridline-color: rgba(255, 255, 255, 0.12);
    color: {tokens["text_main"]};
    selection-background-color: rgba(255, 255, 255, 0.16);
    selection-color: {tokens["text_main"]};
    font-size: {fs(15)}px;
    outline: none;
}}

#tasksDayTable QHeaderView::section {{
    background: rgba({tokens["card_rgb"]}, 230);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: rgba(255, 248, 248, 0.95);
    font-size: {fs(14)}px;
    font-weight: 700;
    padding: 7px 6px;
}}

#tasksDayTable QHeaderView::section:focus {{
    outline: none;
}}

#tasksDayTable::item {{
    padding: 6px 8px;
    border: 0px;
}}

#tasksDayTable::item:focus {{
    outline: none;
}}

#tasksDayTable::item:drop-indicator {{
    border-top: 2px solid {tokens["accent"]};
}}

QPushButton#tasksUnitActionButton {{
    background: rgba(255, 255, 255, 0.10);
    border: 1px solid rgba(255, 255, 255, 0.24);
    border-radius: 6px;
    color: {tokens["text_main"]};
    font-size: {fs(12)}px;
    font-weight: 700;
}}

QPushButton#tasksUnitEditButton {{
    background: rgba(255, 255, 255, 0.10);
    border: 1px solid rgba(255, 255, 255, 0.24);
    border-radius: 6px;
    color: {tokens["text_main"]};
    font-size: {fs(12)}px;
    font-weight: 700;
    padding: 0px;
}}

QPushButton#tasksUnitEditButton:hover {{
    background: rgba(255, 255, 255, 0.22);
}}

QPushButton#tasksUnitActionButton:hover {{
    background: rgba(255, 255, 255, 0.22);
}}

QPushButton#tasksUnitActionButton:disabled,
QPushButton#tasksUnitEditButton:disabled {{
    background: rgba(255, 255, 255, 0.06);
    color: rgba(255, 255, 255, 0.42);
    border-color: rgba(255, 255, 255, 0.12);
}}

#tasksPreviewCard {{
    background: rgba(0, 0, 0, 0.18);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 12px;
}}

#tasksPreviewTitle {{
    color: {tokens["accent"]};
    font-size: {fs(20)}px;
    font-weight: 700;
}}

#tasksPreviewText {{
    color: {tokens["text_main"]};
    font-size: {fs(15)}px;
    font-weight: 500;
}}

#settingsScrollArea,
#settingsScrollArea QWidget {{
    background: transparent;
}}

#settingsScrollArea QScrollBar:vertical {{
    background: rgba(255, 255, 255, 0.08);
    width: 10px;
    margin: 4px 2px 4px 0;
    border-radius: 5px;
}}

#settingsScrollArea QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.30);
    min-height: 36px;
    border-radius: 5px;
}}

#settingsScrollArea QScrollBar::add-line:vertical,
#settingsScrollArea QScrollBar::sub-line:vertical {{
    height: 0px;
}}

#planningTitle,
#settingsPageTitle {{
    color: white;
    font-size: {fs(30)}px;
    font-weight: 700;
}}

#planningText,
#settingsPageHint {{
    color: {tokens["text_main"]};
    font-size: {fs(16)}px;
}}

QPushButton#planningActionButton,
QPushButton#planningHeaderButton {{
    background: {tokens["secondary_bg"]};
    border: 1px solid {tokens["secondary_border"]};
    border-radius: 8px;
    color: {tokens["text_main"]};
    font-size: {fs(16)}px;
    font-weight: 600;
    min-height: 46px;
    padding: 8px 14px;
}}

QPushButton#planningArrowButton {{
    background: {tokens["secondary_bg"]};
    border: 1px solid {tokens["secondary_border"]};
    border-radius: 10px;
    color: {tokens["text_main"]};
    font-size: {fs(30)}px;
    font-weight: 700;
    min-width: 82px;
    min-height: 52px;
    padding: 0px 10px;
}}

QPushButton#planningActionButton:hover,
QPushButton#planningHeaderButton:hover {{
    background: rgba(255, 255, 255, 0.24);
}}

QPushButton#planningActionButton:focus,
QPushButton#planningArrowButton:focus,
QPushButton#planningIconButton:focus {{
    outline: none;
}}

QPushButton#planningArrowButton:hover {{
    background: rgba(255, 255, 255, 0.24);
}}

#planningWeekTitle {{
    color: {tokens["text_main"]};
    font-size: {fs(26)}px;
    font-weight: 700;
}}

#planningWeekTable {{
    background: rgba(0, 0, 0, 0.14);
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 12px;
    gridline-color: rgba(255, 255, 255, 0.14);
    color: {tokens["text_main"]};
    selection-background-color: rgba(255, 255, 255, 0.18);
    selection-color: {tokens["text_main"]};
    font-size: {fs(15)}px;
    alternate-background-color: rgba(255, 255, 255, 0.04);
}}

#planningWeekTable QHeaderView::section {{
    background: rgba({tokens["card_rgb"]}, 236);
    border: 1px solid rgba(255, 255, 255, 0.24);
    color: rgba(255, 247, 247, 0.98);
    font-size: {fs(14)}px;
    font-weight: 700;
    padding: 9px 8px;
}}

#planningWeekTable QHeaderView::section:focus {{
    outline: none;
}}

#planningWeekTable QTableCornerButton::section {{
    background: rgba({tokens["card_rgb"]}, 236);
    border: 1px solid rgba(255, 255, 255, 0.24);
}}

#planningWeekTable {{
    font-size: {fs(15)}px;
    outline: none;
}}

#planningWeekTable::item {{
    padding: 8px;
    border: 0px;
}}

#planningWeekTable::item:focus {{
    outline: none;
}}

QPushButton#planningIconButton {{
    background: {tokens["secondary_bg"]};
    border: 1px solid {tokens["secondary_border"]};
    border-radius: 10px;
    min-width: 40px;
    min-height: 40px;
    color: {tokens["text_main"]};
}}

QPushButton#planningIconButton:hover {{
    background: {tokens["mode_hover"]};
    border-color: rgba(255, 255, 255, 0.28);
}}

QPushButton#planningIconButton:checked {{
    background: {tokens["mode_checked"]};
    border-color: rgba(255, 255, 255, 0.30);
}}

QLabel#planningHelpText {{
    color: rgba(255, 241, 241, 0.86);
    font-size: {fs(14)}px;
    font-weight: 500;
}}

QLabel#planningLegendText {{
    color: rgba(255, 247, 247, 0.92);
    font-size: {fs(14)}px;
    font-weight: 700;
    background: rgba(0, 0, 0, 0.18);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 7px;
    padding: 5px 10px;
}}

QDialog#planningTaskDialog {{
    background: rgba({tokens["card_rgb"]}, 246);
    border: 1px solid rgba(255, 255, 255, 0.20);
    border-radius: 12px;
}}

QLabel#planningTaskLabel {{
    color: {tokens["text_main"]};
    font-size: {fs(16)}px;
    font-weight: 700;
}}

QLineEdit#planningTaskInput,
QSpinBox#planningTaskInput {{
    background: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.26);
    border-radius: 8px;
    color: {tokens["text_main"]};
    font-size: {fs(16)}px;
    padding: 8px 10px;
}}

QSpinBox#planningTaskInput::up-button,
QSpinBox#planningTaskInput::down-button {{
    width: 18px;
}}

QDialog#planningTaskDialog QPushButton {{
    background: {tokens["secondary_bg"]};
    border: 1px solid {tokens["secondary_border"]};
    border-radius: 8px;
    color: {tokens["text_main"]};
    font-size: {fs(15)}px;
    font-weight: 600;
    min-height: 34px;
    padding: 6px 12px;
}}

QDialog#planningTaskDialog QPushButton:hover {{
    background: rgba(255, 255, 255, 0.24);
}}

#settingsPageIcon {{
    color: {tokens["accent"]};
}}

#settingsFormBox {{
    background: rgba(255, 255, 255, 0.09);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 12px;
}}

#settingsFormBox QLabel {{
    color: {tokens["text_main"]};
    font-size: {fs(18)}px;
    font-weight: 600;
}}

#settingsSectionTitle {{
    color: {tokens["accent"]};
    font-size: {fs(24)}px;
    font-weight: 700;
    padding-bottom: 8px;
}}

#settingsFormBox QSpinBox,
#settingsFormBox QComboBox {{
    background: rgba(255, 255, 255, 0.14);
    border: 1px solid rgba(255, 255, 255, 0.24);
    color: white;
    border-radius: 8px;
    font-size: {fs(17)}px;
    min-height: 38px;
    padding: 4px 10px;
}}

#settingsFormBox QComboBox QAbstractItemView {{
    background: rgba(40, 60, 78, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: {tokens["text_main"]};
}}

#settingsFormBox QCheckBox {{
    color: {tokens["text_main"]};
    font-size: {fs(17)}px;
}}

QPushButton#settingsSaveButton,
QPushButton#settingsResetButton,
QPushButton#settingsPreviewButton {{
    border-radius: 8px;
    font-weight: 600;
    min-height: 48px;
    padding: 10px 16px;
}}

QPushButton#settingsSaveButton {{
    background: {tokens["primary_bg"]};
    border: none;
    color: {tokens["primary_fg"]};
    font-size: {fs(17)}px;
    font-weight: 700;
}}

QPushButton#settingsSaveButton:hover {{
    background: rgba(255, 255, 255, 0.92);
}}

QPushButton#settingsResetButton {{
    background: {tokens["secondary_bg"]};
    border: 1px solid {tokens["secondary_border"]};
    color: {tokens["secondary_fg"]};
}}

QPushButton#settingsResetButton:hover {{
    background: rgba(255, 255, 255, 0.24);
}}

QPushButton#settingsPreviewButton {{
    background: rgba(255, 255, 255, 0.16);
    border: 1px solid rgba(255, 255, 255, 0.28);
    color: {tokens["text_main"]};
    min-height: 42px;
    font-size: {fs(15)}px;
}}

QPushButton#settingsPreviewButton:hover {{
    background: rgba(255, 255, 255, 0.28);
}}

QPushButton#settingsPreviewButton:disabled {{
    background: rgba(255, 255, 255, 0.09);
    border: 1px solid rgba(255, 255, 255, 0.16);
    color: rgba(255, 255, 255, 0.55);
}}

#updateFooter {{
    background: rgba(0, 0, 0, 0.20);
    border-top: 1px solid rgba(255, 255, 255, 0.18);
}}

#updateFooterLabel {{
    color: {tokens["text_main"]};
    font-size: {fs(15)}px;
    font-weight: 600;
}}

QPushButton#updateFooterPrimaryButton,
QPushButton#updateFooterSecondaryButton {{
    min-height: 34px;
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 600;
}}

QPushButton#updateFooterPrimaryButton {{
    background: {tokens["primary_bg"]};
    border: none;
    color: {tokens["primary_fg"]};
}}

QPushButton#updateFooterPrimaryButton:hover {{
    background: rgba(255, 255, 255, 0.92);
}}

QPushButton#updateFooterSecondaryButton {{
    background: {tokens["secondary_bg"]};
    border: 1px solid {tokens["secondary_border"]};
    color: {tokens["secondary_fg"]};
}}

QPushButton#updateFooterSecondaryButton:hover {{
    background: rgba(255, 255, 255, 0.24);
}}

#updatesErrorText {{
    color: #FFD4D4;
    font-size: {fs(15)}px;
    font-weight: 600;
}}

#updatesWarningText {{
    color: #FFE9AE;
    font-size: {fs(15)}px;
    font-weight: 600;
}}

QProgressBar#updatesInstallProgressBar {{
    border: 1px solid rgba(255, 255, 255, 0.24);
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.12);
    color: {tokens["text_main"]};
    text-align: center;
    min-height: 18px;
    max-height: 18px;
    font-size: {fs(12)}px;
    font-weight: 700;
}}

QProgressBar#updatesInstallProgressBar::chunk {{
    border-radius: 7px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 {tokens["accent"]},
        stop: 1 rgba(255, 255, 255, 0.88)
    );
}}

QMessageBox {{
    background: rgba({tokens["card_rgb"]}, 248);
}}

QMessageBox QLabel {{
    color: {tokens["text_main"]};
    background: transparent;
    font-size: {fs(15)}px;
}}

QMessageBox QPushButton {{
    min-width: 88px;
    padding: 6px 14px;
    border-radius: 8px;
    background: {tokens["secondary_bg"]};
    border: 1px solid {tokens["secondary_border"]};
    color: {tokens["text_main"]};
    font-size: {fs(14)}px;
    font-weight: 600;
}}

QMessageBox QPushButton:hover {{
    background: rgba(255, 255, 255, 0.20);
}}

QStatusBar {{
    background: transparent;
    color: {tokens["text_main"]};
    font-size: {fs(15)}px;
    font-weight: 600;
    min-height: 30px;
}}

QStatusBar QLabel {{
    font-size: {fs(15)}px;
    font-weight: 600;
}}

#floatingRoot {{
    background: rgba({tokens["card_rgb"]}, 252);
    border: 1px solid {tokens["card_border"]};
    border-radius: 12px;
}}

#floatingTitleBar {{
    background: rgba(0, 0, 0, 0.08);
    border-radius: 7px;
}}

#floatingTimeFrame {{
    background: rgba(0, 0, 0, 0.10);
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 12px;
}}

#floatingTimerLabel {{
    color: white;
    font-size: {fs(48)}px;
    font-weight: 700;
}}

QPushButton#floatingPrimary {{
    background: {tokens["primary_bg"]};
    border: none;
    color: {tokens["primary_fg"]};
    font-size: {fs(16)}px;
    font-weight: 700;
}}

QPushButton#floatingPrimary:hover {{
    background: rgba(255, 255, 255, 0.92);
}}

QPushButton#floatingHeaderAction {{
    background: rgba(255, 255, 255, 0.16);
    border: 1px solid rgba(255, 255, 255, 0.28);
    border-radius: 9px;
    color: {tokens["text_main"]};
    font-size: {fs(13)}px;
    font-weight: 700;
    padding: 4px 12px;
}}

QPushButton#floatingHeaderAction:hover {{
    background: rgba(255, 255, 255, 0.28);
}}

QPushButton#floatingPinButton {{
    background: rgba(255, 255, 255, 0.16);
    border: 1px solid rgba(255, 255, 255, 0.24);
    border-radius: 10px;
    color: {tokens["text_main"]};
}}

QPushButton#floatingPinButton:hover {{
    background: rgba(255, 255, 255, 0.26);
}}

QPushButton#floatingPinButton:checked {{
    background: {tokens["mode_checked"]};
}}

QPushButton#floatingCtrlButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: {tokens["window_ctrl"]};
    font-size: {fs(14)}px;
    font-weight: 600;
}}

QPushButton#floatingCtrlButton:hover {{
    background: {tokens["danger_bg"]};
    border-color: rgba(255, 255, 255, 0.28);
}}

QPushButton#floatingBackButton {{
    background: rgba(255, 255, 255, 0.14);
    border: 1px solid rgba(255, 255, 255, 0.24);
    border-radius: 7px;
    color: {tokens["window_ctrl"]};
    font-size: {fs(15)}px;
    font-weight: 700;
}}

QPushButton#floatingBackButton:hover {{
    background: rgba(255, 255, 255, 0.28);
    border-color: rgba(255, 255, 255, 0.34);
}}

#floatingSizeGrip {{
    background: rgba(255, 255, 255, 0.28);
    border: 1px solid rgba(255, 255, 255, 0.34);
    border-radius: 5px;
}}
"""
