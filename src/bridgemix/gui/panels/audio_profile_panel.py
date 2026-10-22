"""Windows-compatible sample-rate settings for the Linux PipeWire profile."""
from __future__ import annotations

import sys

from PyQt6.QtCore import QProcess, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bridgemix import audio_profile, theme


class AudioProfilePanel(QWidget):
    """Choose the application format and persist it for the user's next login."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._saved_rate = audio_profile.get_sample_rate()
        self._selected_rate = self._saved_rate
        self._process: QProcess | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 26)
        root.setSpacing(16)

        eyebrow = QLabel("BRIDGE CAST V2  /  AUDIO")
        eyebrow.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 10px; font-weight: 700; "
            "letter-spacing: 0.14em; background: transparent;"
        )
        root.addWidget(eyebrow)

        title = QLabel("Application sample rate")
        title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 25px; font-weight: 650; background: transparent;"
        )
        root.addWidget(title)

        subtitle = QLabel(
            "Match the Windows driver format while keeping the existing USB audio path stable."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;"
        )
        root.addWidget(subtitle)

        root.addWidget(self._signal_path())

        mode_label = QLabel("FORMAT")
        mode_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 10px; font-weight: 700; "
            "letter-spacing: 0.12em; background: transparent;"
        )
        root.addWidget(mode_label)

        self._choice_group = QButtonGroup(self)
        self._choice_group.setExclusive(True)
        self._cards: dict[int, QPushButton] = {}
        choices = QVBoxLayout()
        choices.setSpacing(9)
        self._make_option(
            choices,
            48_000,
            "48 kHz",
            "USB native",
            "Use the device's standard transport directly.",
        )
        self._make_option(
            choices,
            96_000,
            "96 kHz",
            "Windows-compatible",
            "Expose stereo 96 kHz endpoints; PipeWire converts to and from USB 48 kHz.",
        )
        root.addLayout(choices)

        footer = QHBoxLayout()
        footer.setSpacing(14)
        self._status_dot = QFrame()
        self._status_dot.setFixedSize(8, 8)
        self._status_dot.setStyleSheet(
            f"background: {theme.GREEN}; border: none; border-radius: 4px;"
        )
        footer.addWidget(self._status_dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        footer.addWidget(self._status, stretch=1)
        self._apply = QPushButton()
        self._apply.setObjectName("btn_primary")
        self._apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply.clicked.connect(self._apply_selection)
        footer.addWidget(self._apply)
        root.addLayout(footer)
        root.addStretch()

        self._sync_selection(self._saved_rate)
        self._refresh_status()

    def _signal_path(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("audio_signal_path")
        frame.setStyleSheet(
            f"QFrame#audio_signal_path {{ background: {theme.SURFACE}; "
            "border: 1px solid rgba(255,255,255,0.07); border-radius: 10px; }"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(17, 13, 17, 13)
        row.setSpacing(17)

        self._app_rate = QLabel()
        self._app_rate.setFixedWidth(82)
        self._app_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._app_rate.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 21px; font-weight: 700; background: transparent;"
        )
        row.addWidget(self._app_rate)

        app_info = QVBoxLayout()
        app_name = QLabel("APPLICATIONS")
        app_name.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 10px; font-weight: 700; "
            "letter-spacing: 0.08em; background: transparent;"
        )
        app_detail = QLabel("Stereo float32 endpoint")
        app_detail.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        app_info.addWidget(app_name)
        app_info.addWidget(app_detail)
        row.addLayout(app_info, stretch=1)

        bridge = QLabel("PIPEWIRE\nCONVERSION")
        bridge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bridge.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 9px; font-weight: 700; "
            "letter-spacing: 0.06em; background: transparent;"
        )
        row.addWidget(bridge)

        usb_info = QVBoxLayout()
        usb_name = QLabel("BRIDGE CAST USB")
        usb_name.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 10px; font-weight: 700; "
            "letter-spacing: 0.08em; background: transparent;"
        )
        usb_detail = QLabel("14 playback / 6 capture channels")
        usb_detail.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        usb_info.addWidget(usb_name)
        usb_info.addWidget(usb_detail)
        row.addLayout(usb_info, stretch=1)

        usb_rate = QLabel("48 kHz")
        usb_rate.setFixedWidth(82)
        usb_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        usb_rate.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 18px; font-weight: 650; background: transparent;"
        )
        row.addWidget(usb_rate)
        return frame

    def _make_option(
        self,
        layout: QVBoxLayout,
        rate: int,
        title: str,
        tag: str,
        detail: str,
    ) -> None:
        option = QPushButton()
        option.setObjectName("audio_rate_option")
        option.setCheckable(True)
        option.setMinimumHeight(74)
        option.setCursor(Qt.CursorShape.PointingHandCursor)
        option.setAccessibleName(f"{title}, {tag}")
        option.setToolTip(detail)
        option.setStyleSheet(
            f"QPushButton#audio_rate_option {{ background: {theme.SURFACE}; "
            "border: 1px solid rgba(255,255,255,0.07); border-radius: 9px; text-align: left; }"
            f"QPushButton#audio_rate_option:hover {{ background: {theme.SURFACE_2}; "
            "border-color: rgba(255,255,255,0.16); }"
            f"QPushButton#audio_rate_option:checked {{ background: {theme.SURFACE_2}; "
            f"border: 1px solid {theme.ACCENT}; }}"
        )
        option_row = QHBoxLayout(option)
        option_row.setContentsMargins(15, 9, 16, 9)
        option_row.setSpacing(13)

        rate_value = QLabel(title)
        rate_value.setFixedWidth(82)
        rate_value.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 18px; font-weight: 700; background: transparent;"
        )
        option_row.addWidget(rate_value)

        description = QVBoxLayout()
        tag_label = QLabel(tag)
        tag_label.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 11px; font-weight: 650; background: transparent;"
        )
        detail_label = QLabel(detail)
        detail_label.setWordWrap(True)
        detail_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 10px; background: transparent;"
        )
        description.addWidget(tag_label)
        description.addWidget(detail_label)
        option_row.addLayout(description, stretch=1)

        self._choice_group.addButton(option, rate)
        self._cards[rate] = option
        option.clicked.connect(lambda _checked=False, value=rate: self._select_rate(value))
        layout.addWidget(option)

    def _sync_selection(self, rate: int) -> None:
        card = self._cards.get(rate)
        if card is not None:
            card.setChecked(True)
        self._selected_rate = rate
        self._update_apply_button()

    def _select_rate(self, rate: int) -> None:
        self._selected_rate = rate
        self._app_rate.setText(f"{rate // 1000} kHz")
        self._update_apply_button()

    def _update_apply_button(self) -> None:
        self._apply.setText("Apply 96 kHz" if self._selected_rate == 96_000 else "Apply 48 kHz")
        enabled, active = audio_profile.service_state()
        desired = self._selected_rate == 96_000
        already_applied = (enabled and active) if desired else (not enabled and not active)
        self._apply.setEnabled(self._selected_rate != self._saved_rate or not already_applied)

    def _refresh_status(self) -> None:
        enabled, active = audio_profile.service_state()
        if self._saved_rate == 96_000 and enabled and active:
            self._status.setText("96 kHz active · restored automatically at login")
        elif self._saved_rate == 96_000:
            self._status.setText("96 kHz saved · audio service is not running")
        else:
            self._status.setText("48 kHz selected · Windows-style endpoints are off")
        self._status_dot.setStyleSheet(
            f"background: {theme.GREEN if active else theme.TEXT_FAINT}; border: none; border-radius: 4px;"
        )
        self._app_rate.setText(f"{self._selected_rate // 1000} kHz")
        self._update_apply_button()

    def _apply_selection(self) -> None:
        if self._process is not None:
            return
        _, active = audio_profile.service_state()
        if self._selected_rate == 48_000 and active:
            reply = QMessageBox.warning(
                self,
                "Stop 96 kHz endpoints?",
                "Applications using the virtual 96 kHz endpoints may be disconnected. Continue?",
                QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Apply:
                self._sync_selection(self._saved_rate)
                return
        self._apply.setEnabled(False)
        self._status.setText("Applying the audio profile and login setting…")
        process = QProcess(self)
        self._process = process
        process.setProgram(sys.executable)
        process.setArguments(["-m", "bridgemix.audio_profile", "apply-rate", str(self._selected_rate)])
        process.finished.connect(self._on_apply_finished)
        process.errorOccurred.connect(self._on_apply_error)
        process.start()

    def _on_apply_finished(self, exit_code: int, exit_status) -> None:
        process = self._process
        if process is None:
            return
        output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        error = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        success = exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit
        self._finish_apply(process, success, output or error)

    def _on_apply_error(self, error) -> None:
        process = self._process
        if process is None or error != QProcess.ProcessError.FailedToStart:
            return
        self._finish_apply(process, False, "Could not start the audio-profile command.")

    def _finish_apply(self, process: QProcess, success: bool, message: str) -> None:
        if process is not self._process:
            return
        self._process = None
        process.deleteLater()
        if success:
            self._saved_rate = audio_profile.get_sample_rate()
            self._sync_selection(self._saved_rate)
            self._refresh_status()
            if message:
                self._status.setText(message)
        else:
            self._saved_rate = audio_profile.get_sample_rate()
            self._sync_selection(self._saved_rate)
            self._refresh_status()
            QMessageBox.warning(
                self,
                "Audio Profile",
                message or "The PipeWire profile could not be applied.",
            )
