from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .analysis import ProducerAnalysisRunner
from .bundles import PublicBundleCache
from .equipment import EquipmentMergeConflictError
from .imports import (
    ManualImportAdapter,
    OcrDraft,
    RapidOcrEngine,
    StructuredImportAdapter,
    confirm_import,
    proposal_from_ocr_mapping,
    read_ocr_image,
)
from .lifecycle import ProfileLifecycle
from .models import EquipmentIdentity, ImportProposal, SourceKind
from .profiles import ProfileRepository, ProfileSummary
from .planner import LocalPlannerProcess, bundled_planner_command
from .public_profile import MihomoPublicProfileClient, PublicProfileSelection
from .reports import AnalysisReport, ReportLifecycle, ReportValidity
from .storage import EncryptedPrivateStore
from .synthetic_demo import SyntheticDemoContext, prepare_synthetic_demo
from .tasks import AnalysisTaskDraft, TaskRepository


class _Signals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _ProfileFetchSignals(QObject):
    completed = Signal(object, object)
    failed = Signal(str, object)
    cancelled = Signal(object)


class _OcrSignals(QObject):
    completed = Signal(object, object)
    failed = Signal(str, object)
    cancelled = Signal(object)


class _ProgressBus(QObject):
    updated = Signal(str, int)


class _SyntheticAnalysisSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _SyntheticAnalysisWorker(QRunnable):
    def __init__(self, context: SyntheticDemoContext, lifecycle: ProfileLifecycle,
                 store: EncryptedPrivateStore) -> None:
        super().__init__()
        self.context = context
        self.lifecycle = lifecycle
        self.store = store
        self.signals = _SyntheticAnalysisSignals()

    def run(self) -> None:
        try:
            runner = ProducerAnalysisRunner(
                LocalPlannerProcess(
                    bundled_planner_command(),
                    frozenset({"starhelp.producers.v0.1", "starhelp.local-profile.v0.2"}),
                ),
                ReportLifecycle(self.store, self.lifecycle),
            )
            execution = runner.run(
                request=self.context.request,
                profile_id=self.context.profile.profile_id,
                authorization_generation=self.context.profile.generation,
                lifecycle=self.lifecycle,
            )
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.completed.emit(execution)


class _ProfileFetchWorker(QRunnable):
    def __init__(self, client: MihomoPublicProfileClient, selection: PublicProfileSelection,
                 cancelled: Any) -> None:
        super().__init__()
        self.client = client
        self.selection = selection
        self.cancelled = cancelled
        self.signals = _ProfileFetchSignals()

    def run(self) -> None:
        if self.cancelled.is_set():
            self.signals.cancelled.emit(self.cancelled)
            return
        try:
            proposal = self.client.fetch(self.selection)
        except Exception as exc:
            if self.cancelled.is_set():
                self.signals.cancelled.emit(self.cancelled)
            else:
                self.signals.failed.emit(str(exc), self.cancelled)
            return
        if self.cancelled.is_set():
            self.signals.cancelled.emit(self.cancelled)
            return
        self.signals.completed.emit(proposal, self.cancelled)


class _OcrWorker(QRunnable):
    def __init__(self, image_bytes: bytes, cancelled: threading.Event) -> None:
        super().__init__()
        self.image_bytes = image_bytes
        self.cancelled = cancelled
        self.signals = _OcrSignals()

    def run(self) -> None:
        if self.cancelled.is_set():
            self.signals.cancelled.emit(self.cancelled)
            self.image_bytes = b""
            return
        try:
            draft = RapidOcrEngine().recognize(self.image_bytes)
        except Exception as exc:
            if self.cancelled.is_set():
                self.signals.cancelled.emit(self.cancelled)
            else:
                self.signals.failed.emit(str(exc), self.cancelled)
        else:
            if self.cancelled.is_set():
                self.signals.cancelled.emit(self.cancelled)
            else:
                self.signals.completed.emit(draft, self.cancelled)
        finally:
            self.image_bytes = b""


class _Page(QWidget):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        if subtitle:
            description = QLabel(subtitle)
            description.setWordWrap(True)
            description.setObjectName("pageSubtitle")
            layout.addWidget(description)
        self.content = QVBoxLayout()
        layout.addLayout(self.content, 1)


class TaskPage(_Page):
    temporary_report_ready = Signal(object)

    def __init__(self, profiles: ProfileRepository, tasks: TaskRepository,
                 progress_bus: _ProgressBus, lifecycle: ProfileLifecycle,
                 store: EncryptedPrivateStore) -> None:
        super().__init__(
            "任务",
            "常规任务仅加密记忆目标；生产规划仍待 M0 接通。单独的合成联调按钮只运行内置 fixture。",
        )
        self.profiles = profiles
        self.tasks = tasks
        self.progress_bus = progress_bus
        self.lifecycle = lifecycle
        self.store = store
        self.thread_pool = QThreadPool.globalInstance()
        self._demo_worker: _SyntheticAnalysisWorker | None = None
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(["混沌回忆", "虚构叙事", "末日幻影"])
        self.cycle = QLineEdit()
        self.cycle.setPlaceholderText("输入已核实周期标识")
        self.stage = QLineEdit()
        self.stage.setPlaceholderText("输入已核实关卡标识")
        self.goal = QComboBox()
        self.goal.addItems(["先通关", "达到奖励档位", "提高成绩"])
        self.profile = QComboBox()
        self.fixed = QLineEdit()
        self.fixed.setPlaceholderText("公共角色 ID，以逗号分隔")
        self.excluded = QLineEdit()
        self.excluded.setPlaceholderText("公共角色 ID，以逗号分隔")
        self.locked = QLineEdit()
        self.locked.setPlaceholderText("从所选档案的当前装备快照中选择")
        self.choose_locked_equipment = QPushButton("选择装备…")
        lock_row = QWidget()
        lock_layout = QHBoxLayout(lock_row)
        lock_layout.setContentsMargins(0, 0, 0, 0)
        lock_layout.addWidget(self.locked, 1)
        lock_layout.addWidget(self.choose_locked_equipment)
        for label, widget in (("玩法", self.mode), ("周期", self.cycle), ("关卡", self.stage),
                              ("目标", self.goal), ("本地档案", self.profile),
                              ("固定角色", self.fixed), ("排除角色", self.excluded)):
            form.addRow(label, widget)
        form.addRow("锁定装备", lock_row)
        self.content.addLayout(form)
        self.status = QLabel("尚未创建任务。公共 ID 与条件语义仍需 M0 核验。")
        self.status.setWordWrap(True)
        self.content.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.content.addWidget(self.progress)
        row = QHBoxLayout()
        self.refresh_profiles = QPushButton("刷新档案列表")
        self.analyze = QPushButton("创建分析任务")
        self.synthetic_demo = QPushButton("运行合成联调演示（仅 fixture）")
        self.synthetic_demo.setToolTip(
            "只读取随应用分发并校验摘要的合成数据与测试公钥；不读取所选档案，不访问网络。"
        )
        row.addWidget(self.refresh_profiles)
        row.addWidget(self.analyze)
        self.content.addLayout(row)
        self.content.addWidget(self.synthetic_demo)
        self.refresh_profiles.clicked.connect(self.reload_profiles)
        self.analyze.clicked.connect(self.create_task)
        self.synthetic_demo.clicked.connect(self.run_synthetic_demo)
        self.choose_locked_equipment.clicked.connect(self.open_equipment_lock_picker)
        self.profile.currentIndexChanged.connect(self.restore_last_task)
        self.reload_profiles()

    def run_synthetic_demo(self) -> None:
        if self._demo_worker is not None:
            return
        choice = QMessageBox.question(
            self,
            "运行合成联调演示",
            "将只使用应用内置并校验摘要的 A 签名 fixture、测试公钥和合成 B 快照，"
            "创建或复用一个单独的加密演示档案；不会读取当前所选真实档案，也不会访问网络。"
            "演示档案可在“账号与导入”页撤权并删除。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        self.synthetic_demo.setEnabled(False)
        self.status.setText("正在验证内置合成 fixture…")
        self.progress.setRange(0, 0)
        try:
            context = prepare_synthetic_demo(self.profiles)
            scope = context.task["scope"]
            public_goal = context.task["public_goal"]
            draft = AnalysisTaskDraft.create(
                profile_id=context.profile.profile_id,
                authorization_generation=context.profile.generation,
                mode_label=scope["mode_id"],
                cycle_id=scope["cycle_id"],
                stage_id=scope["stage_id"],
                goal_label=public_goal["kind"],
            )
            self.tasks.save_last(draft)
        except Exception as exc:
            self.synthetic_demo.setEnabled(True)
            self.progress.setRange(0, 100)
            self.status.setText(f"合成演示未启动：{exc}")
            self.progress_bus.updated.emit("合成联调演示未启动。", 0)
            return

        self.reload_profiles()
        index = self.profile.findData(str(context.profile.profile_id))
        if index >= 0:
            self.profile.setCurrentIndex(index)
        self.status.setText("合成演示档案已准备；本地规划器正在分析 fixture 数据…")
        self.progress_bus.updated.emit("仅合成 fixture：本地规划分析进行中。", -1)
        worker = _SyntheticAnalysisWorker(context, self.lifecycle, self.store)
        worker.signals.completed.connect(self._synthetic_demo_completed)
        worker.signals.failed.connect(self._synthetic_demo_failed)
        self._demo_worker = worker
        self.thread_pool.start(worker)

    def _synthetic_demo_completed(self, execution: object) -> None:
        self._demo_worker = None
        self.synthetic_demo.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        report = getattr(execution, "temporary_report", None)
        if report is not None:
            report = replace(
                report,
                task={**report.task, "synthetic_demo": True},
            )
            self.status.setText(
                "合成联调完成：报告仅待在报告页预览，尚未保存。"
                "此结果仅来自 fixture，不代表真实游戏建议。"
            )
            self.progress_bus.updated.emit("合成 fixture 分析完成；报告待用户主动保存。", 100)
            self.temporary_report_ready.emit(report)
            return
        result = getattr(execution, "planner_result", None)
        status = getattr(result, "result", {}).get("status", "unknown")
        self.status.setText(f"合成演示结束，没有可展示的报告（状态：{status}）。")
        self.progress_bus.updated.emit("合成 fixture 分析结束，没有生成报告。", 100)

    def _synthetic_demo_failed(self, message: str) -> None:
        self._demo_worker = None
        self.synthetic_demo.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status.setText(f"合成联调失败：{message}。演示档案可在账号页撤权。")
        self.progress_bus.updated.emit("合成联调失败；没有报告可保存。", 0)

    def reload_profiles(self) -> None:
        selected = self.profile.currentData()
        self.profile.clear()
        for profile in self.profiles.list_profiles():
            self.profile.addItem(profile.label, str(profile.profile_id))
        index = self.profile.findData(selected)
        if index >= 0:
            self.profile.setCurrentIndex(index)

    def showEvent(self, event: object) -> None:
        super().showEvent(event)
        self.reload_profiles()

    def create_task(self) -> None:
        if not self.cycle.text().strip() or not self.stage.text().strip():
            QMessageBox.information(self, "需要关卡范围", "请填写已核实的周期和关卡标识。")
            return
        if self.profile.currentIndex() < 0:
            QMessageBox.information(self, "需要本地档案", "请先创建并授权一个本地档案。")
            return
        profile_id = self.profile.currentData()
        profile = next((item for item in self.profiles.list_profiles()
                        if str(item.profile_id) == profile_id), None)
        if profile is None:
            QMessageBox.warning(self, "档案不可用", "所选档案已撤权或不存在，请刷新档案列表。")
            self.reload_profiles()
            return
        requested_locks = tuple(
            item.strip() for item in self.locked.text().split(",") if item.strip()
        )
        if requested_locks:
            try:
                snapshot = self.profiles.load_snapshot(profile.profile_id, profile.generation)
            except FileNotFoundError:
                QMessageBox.warning(self, "装备锁定不可用", "此档案没有当前装备快照，请先导入并确认。")
                return
            except (PermissionError, ValueError) as exc:
                QMessageBox.warning(self, "装备锁定不可用", str(exc))
                self.reload_profiles()
                return
            available_ids = {str(item.local_instance_id) for item in snapshot.equipment}
            missing_ids = set(requested_locks) - available_ids
            if missing_ids:
                QMessageBox.warning(
                    self,
                    "装备锁定已过期",
                    "锁定列表中有装备已不在此档案的当前快照。请重新选择装备后再创建任务。",
                )
                return
        try:
            task = AnalysisTaskDraft.create(
                profile_id=profile.profile_id,
                authorization_generation=profile.generation,
                mode_label=self.mode.currentText(),
                cycle_id=self.cycle.text(),
                stage_id=self.stage.text(),
                goal_label=self.goal.currentText(),
                fixed_character_ids=self.fixed.text(),
                excluded_character_ids=self.excluded.text(),
                locked_equipment_instance_ids=self.locked.text(),
            )
            self.tasks.save_last(task)
        except (PermissionError, ValueError) as exc:
            QMessageBox.warning(self, "无法创建任务", str(exc))
            return
        self._show_waiting_task(task)

    def open_equipment_lock_picker(self) -> None:
        profile_id = self.profile.currentData()
        profile = next((item for item in self.profiles.list_profiles()
                        if str(item.profile_id) == profile_id), None)
        if profile is None:
            QMessageBox.information(self, "需要本地档案", "先选择一个已授权档案。")
            return
        try:
            snapshot = self.profiles.load_snapshot(profile.profile_id, profile.generation)
        except FileNotFoundError:
            QMessageBox.information(
                self, "没有装备快照", "此档案尚无已确认的装备实例导入。"
            )
            return
        except (PermissionError, ValueError) as exc:
            QMessageBox.warning(self, "装备资料不可用", str(exc))
            return
        if not snapshot.equipment:
            QMessageBox.information(self, "没有装备实例", "此档案当前快照中没有装备实例。")
            return

        selected_ids = {
            value.strip() for value in self.locked.text().split(",") if value.strip()
        }
        dialog = QDialog(self)
        dialog.setWindowTitle("选择锁定的装备实例")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "仅列出此档案当前快照中的本地实例。未确认身份的装备仍可锁定当前记录，"
            "但不会因此获得跨角色调装资格。"
        ))
        choices = QListWidget(dialog)
        choices.setObjectName("equipmentLockChoices")
        for equipment in snapshot.equipment:
            owner = f"角色 {equipment.owner_character_id}" \
                if equipment.owner_character_id else "未识别角色"
            instance_id = str(equipment.local_instance_id)
            item = QListWidgetItem(
                f"{equipment.slot} · 类型 {equipment.public_type_id} · {owner} · "
                f"身份 {equipment.identity.value} · 实例 {instance_id}",
                choices,
            )
            item.setData(Qt.ItemDataRole.UserRole, instance_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if instance_id in selected_ids else Qt.CheckState.Unchecked
            )
        layout.addWidget(choices)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        locked_ids = [
            choices.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(choices.count())
            if choices.item(index).checkState() == Qt.CheckState.Checked
        ]
        self.locked.setText(", ".join(locked_ids))

    def restore_last_task(self, *_args: object) -> None:
        profile_id = self.profile.currentData()
        if profile_id is None:
            self._clear_task_selection("先选择一个已授权档案，任务目标会按档案分别记忆。")
            return
        profile = next((item for item in self.profiles.list_profiles()
                        if str(item.profile_id) == profile_id), None)
        if profile is None:
            self._clear_task_selection("所选档案不可用，请刷新档案列表。")
            return
        try:
            task = self.tasks.load_last(profile.profile_id, profile.generation)
        except (PermissionError, ValueError) as exc:
            self._clear_task_selection(f"无法恢复上次任务：{exc}")
            return
        if task is None:
            self._clear_task_selection("此档案还没有记忆的任务目标。生产规划尚待 M0 接通。")
            return
        mode_index = self.mode.findText(task.mode_label)
        goal_index = self.goal.findText(task.goal_label)
        if mode_index >= 0:
            self.mode.setCurrentIndex(mode_index)
        if goal_index >= 0:
            self.goal.setCurrentIndex(goal_index)
        self.cycle.setText(task.cycle_id)
        self.stage.setText(task.stage_id)
        self.fixed.setText(", ".join(task.fixed_character_ids))
        self.excluded.setText(", ".join(task.excluded_character_ids))
        self.locked.setText(", ".join(task.locked_equipment_instance_ids))
        self._show_waiting_task(task)

    def _clear_task_selection(self, status: str) -> None:
        self.mode.setCurrentIndex(0)
        self.goal.setCurrentIndex(0)
        self.cycle.clear()
        self.stage.clear()
        self.fixed.clear()
        self.excluded.clear()
        self.locked.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status.setText(status)

    def _show_waiting_task(self, task: AnalysisTaskDraft) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(task.progress)
        self.status.setText(
            f"目标已按本地档案加密记忆（任务 {str(task.task_id)[:8]}）。"
            "生产分析尚待 M0 接通；账号数据未发送，也没有生成生产建议。"
        )
        self.progress_bus.updated.emit(
            "本地任务已记录，等待生产分析接入；没有生成生产建议。", task.progress
        )


class AccountsPage(_Page):
    def __init__(self, repository: ProfileRepository, lifecycle: ProfileLifecycle,
                 progress_bus: _ProgressBus) -> None:
        super().__init__("账号与导入", "每档案独立授权。公开 UID 只在确认后直连选定服务，读取结果先预览。")
        self.repository = repository
        self.lifecycle = lifecycle
        self.progress_bus = progress_bus
        self.thread_pool = QThreadPool.globalInstance()
        self.pending: ImportProposal | None = None
        self.pending_profile: ProfileSummary | None = None
        self.fetch_profile: ProfileSummary | None = None
        self.pending_cancel: Any = None
        self.pending_auto_refresh = False
        self.auto_refresh_running = False
        self.ocr_draft: OcrDraft | None = None
        self.ocr_profile: ProfileSummary | None = None
        self.ocr_cancel: threading.Event | None = None
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.profile_list = QComboBox()
        self.label = QLineEdit()
        self.label.setPlaceholderText("本地档案名称")
        self.uid = QLineEdit()
        self.uid.setPlaceholderText("手动查询临时使用；单独启用自动刷新后才会加密保存")
        self.server = QLineEdit()
        self.server.setPlaceholderText("明确选择/填写服务区；实际 UID 映射仍待 M0 核实")
        self.confirm_consent = QCheckBox(
            "我确认此 UID、区服、Mihomo 服务商和展示数据用途；请求会发送 UID、固定语言/接口版本，"
            "服务也会看到网络来源地址；区服字段留在本机且服务端映射尚待核实。只读取公开展示档案，"
            "结果在本机预览，"
            "我可随时撤权并删除本档案资料。"
        )
        self.auto_refresh_consent = QCheckBox(
            "单独允许应用运行期间自动查询：启用时立即读取一次，此后每 24 小时最多一次；"
            "UID 将以当前 Windows 用户加密保存，"
            "结果仍需预览并确认导入，可随时关闭"
        )
        self.save_auto_refresh_button = QPushButton("保存自动刷新授权")
        self.fetch_button = QPushButton("确认并读取公开档案")
        self.cancel_fetch_button = QPushButton("取消读取")
        self.cancel_fetch_button.setEnabled(False)
        self.local_button = QPushButton("创建本地空档案")
        self.import_button = QPushButton("预览结构化 JSON")
        self.manual_path = QLineEdit()
        self.manual_path.setPlaceholderText("字段路径，例如 character:101.level")
        self.manual_value = QLineEdit()
        self.manual_value.setPlaceholderText("玩家确认后的字段值")
        self.manual_button = QPushButton("预览手动字段")
        self.ocr_button = QPushButton("本机 OCR 预览截图")
        self.ocr_candidate = QComboBox()
        self.map_ocr_button = QPushButton("将 OCR 行映射到手动字段")
        self.save_button = QPushButton("确认预览并保存")
        self.revoke_button = QPushButton("撤权并删除本地档案")
        self.equipment_list = QComboBox()
        self.confirm_equipment_button = QPushButton("确认所选装备实例")
        self.equipment_link_target = QComboBox()
        self.link_equipment_button = QPushButton("确认合并为同一件")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        form = QFormLayout()
        form.addRow("现有档案", self.profile_list)
        form.addRow("档案名称", self.label)
        form.addRow("UID", self.uid)
        form.addRow("区服", self.server)
        form.addRow("手动字段路径", self.manual_path)
        form.addRow("手动字段值", self.manual_value)
        self.content.addLayout(form)
        self.content.addWidget(self.confirm_consent)
        refresh_row = QHBoxLayout()
        refresh_row.addWidget(self.auto_refresh_consent, 1)
        refresh_row.addWidget(self.save_auto_refresh_button)
        self.content.addLayout(refresh_row)
        row = QHBoxLayout()
        for button in (self.fetch_button, self.cancel_fetch_button, self.local_button,
                       self.import_button, self.manual_button,
                       self.ocr_button, self.map_ocr_button,
                       self.save_button, self.revoke_button):
            row.addWidget(button)
        self.content.addLayout(row)
        self.content.addWidget(self.ocr_candidate)
        equipment_row = QHBoxLayout()
        equipment_row.addWidget(QLabel("装备身份"))
        equipment_row.addWidget(self.equipment_list, 1)
        equipment_row.addWidget(self.confirm_equipment_button)
        self.content.addLayout(equipment_row)
        link_row = QHBoxLayout()
        link_row.addWidget(QLabel("将所选装备记录并入"))
        link_row.addWidget(self.equipment_link_target, 1)
        link_row.addWidget(self.link_equipment_button)
        self.content.addLayout(link_row)
        self.content.addWidget(self.progress)
        self.content.addWidget(self.preview, 1)
        self.fetch_button.clicked.connect(self.fetch_public)
        self.cancel_fetch_button.clicked.connect(self.cancel_public_fetch)
        self.local_button.clicked.connect(self.create_local)
        self.import_button.clicked.connect(self.preview_structured)
        self.manual_button.clicked.connect(self.preview_manual)
        self.ocr_button.clicked.connect(self.choose_image)
        self.map_ocr_button.clicked.connect(self.map_ocr_line)
        self.save_button.clicked.connect(self.save_preview)
        self.revoke_button.clicked.connect(self.revoke_selected)
        self.confirm_equipment_button.clicked.connect(self.confirm_equipment_identity)
        self.link_equipment_button.clicked.connect(self.link_equipment_identity)
        self.save_auto_refresh_button.clicked.connect(self.save_auto_refresh_setting)
        self.uid.textChanged.connect(self._auto_refresh_uid_edited)
        self.equipment_list.currentIndexChanged.connect(self._update_equipment_confirmation_enabled)
        self.equipment_list.currentIndexChanged.connect(self._reload_equipment_link_targets)
        self.equipment_link_target.currentIndexChanged.connect(self._update_equipment_link_enabled)
        self.profile_list.currentIndexChanged.connect(self._selection_changed)
        self._reload_profiles()
        self._selection_changed()
        self.auto_refresh_timer = QTimer(self)
        self.auto_refresh_timer.setInterval(15 * 60 * 1000)
        self.auto_refresh_timer.timeout.connect(self._run_due_auto_refreshes)
        self.auto_refresh_timer.start()
        QTimer.singleShot(0, self._run_due_auto_refreshes)

    def _reload_profiles(self) -> None:
        selected = self.profile_list.currentData()
        self.profile_list.clear()
        self.profile_list.addItem("新建档案…", None)
        for profile in self.repository.list_profiles():
            self.profile_list.addItem(profile.label, str(profile.profile_id))
        index = self.profile_list.findData(selected)
        self.profile_list.setCurrentIndex(index if index >= 0 else 0)

    def _selected_profile(self) -> ProfileSummary | None:
        profile_id = self.profile_list.currentData()
        if profile_id is None:
            return None
        return next((item for item in self.repository.list_profiles()
                     if str(item.profile_id) == profile_id), None)

    def _selection_changed(self, *_args: object) -> None:
        profile = self._selected_profile()
        if self.fetch_profile is not None and not self._same_profile_generation(
            self.fetch_profile, profile
        ):
            cancel = self.pending_cancel
            if cancel is not None:
                cancel.set()
                self._fetch_cancelled(cancel)
                self.progress_bus.updated.emit("切换档案后已丢弃旧档案查询结果。", 0)
                self.preview.setPlainText(
                    "已切换档案；旧档案公开查询已取消，任何迟到结果都会被丢弃。"
                )
        if self.ocr_profile is not None and not self._same_profile_generation(
            self.ocr_profile, profile
        ):
            self._discard_ocr_preview("已切换档案，旧档案的 OCR 候选已丢弃。")
        if (
            self.pending is not None
            and self.pending_profile is not None
            and not self._same_profile_generation(self.pending_profile, profile)
        ):
            self.pending = None
            self.pending_profile = None
            self.save_button.setEnabled(False)
            self.progress_bus.updated.emit("切换档案后已清除旧档案导入预览。", 0)
            self.preview.setPlainText("已切换档案；旧档案导入预览已清除，请重新导入。")
        self.revoke_button.setEnabled(profile is not None)
        if profile is None:
            self.auto_refresh_consent.setChecked(False)
            self.uid.clear()
        else:
            try:
                config = self.repository.auto_refresh_config(profile.profile_id, profile.generation)
            except Exception:
                config = None
            self.auto_refresh_consent.setChecked(config is not None)
            self.uid.setText(config["uid"] if config else "")
            self.server.setText(profile.server_label)
        self._reload_equipment()

    @staticmethod
    def _same_profile_generation(
        first: ProfileSummary | None, second: ProfileSummary | None
    ) -> bool:
        return bool(
            first is not None
            and second is not None
            and first.profile_id == second.profile_id
            and first.generation == second.generation
        )

    def _discard_ocr_preview(self, message: str | None = None) -> None:
        profile = self.ocr_profile
        cancel = self.ocr_cancel
        self.ocr_cancel = None
        if cancel is not None:
            cancel.set()
            if profile is not None:
                self.lifecycle.unregister_task(profile.profile_id, profile.generation, cancel)
        self.ocr_profile = None
        self.ocr_draft = None
        self.ocr_candidate.clear()
        if self.pending is not None and self.pending.source_kind is SourceKind.OCR:
            self.pending = None
            self.pending_profile = None
            self.save_button.setEnabled(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.ocr_button.setEnabled(True)
        if message is not None:
            self.progress_bus.updated.emit(message, 0)
            self.preview.setPlainText(message)

    def _finish_ocr_task(self, cancel: threading.Event) -> bool:
        if self.ocr_cancel is not cancel:
            return False
        self.ocr_cancel = None
        profile = self.ocr_profile
        if profile is not None:
            self.lifecycle.unregister_task(profile.profile_id, profile.generation, cancel)
        return True

    def save_auto_refresh_setting(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            QMessageBox.information(self, "需要档案", "先创建或选择一个 Mihomo 公开档案。")
            return
        enabled = self.auto_refresh_consent.isChecked()
        try:
            if enabled and self.server.text().strip() != profile.server_label:
                raise ValueError("区服与当前档案不一致，请创建独立档案后再授权。")
            self.repository.set_auto_refresh(
                profile.profile_id,
                enabled,
                separately_confirmed=enabled,
                uid=self.uid.text().strip() if enabled else None,
            )
        except Exception as exc:
            QMessageBox.warning(self, "自动刷新授权未保存", str(exc))
            return
        if self.pending_auto_refresh and self.fetch_profile == profile:
            if self.pending_cancel is not None:
                self.pending_cancel.set()
            self.pending_cancel = None
            self.fetch_profile = None
            self.pending_profile = None
            self.pending = None
            self.pending_auto_refresh = False
            self.auto_refresh_running = False
            self.fetch_button.setEnabled(True)
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
        if enabled:
            self._run_due_auto_refreshes()
            self.preview.setPlainText(
                "自动刷新已启用：本档案 UID 以当前 Windows 用户加密保存，每 24 小时最多查询一次；"
                "新数据仍需预览并确认导入。"
            )
        else:
            self.preview.setPlainText("自动刷新已关闭；加密保存的 UID 已删除。")

    def _auto_refresh_uid_edited(self, value: str) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        try:
            config = self.repository.auto_refresh_config(profile.profile_id, profile.generation)
        except Exception:
            return
        if config is not None and value.strip() != config["uid"]:
            self.auto_refresh_consent.setChecked(False)

    def _run_due_auto_refreshes(self) -> None:
        if self.auto_refresh_running or self.pending_cancel is not None:
            return
        now = datetime.now(UTC)
        for profile in self.repository.list_profiles():
            if not profile.auto_refresh or profile.provider_id != MihomoPublicProfileClient.PROVIDER_ID:
                continue
            try:
                config = self.repository.auto_refresh_config(profile.profile_id, profile.generation)
                last_attempt = (
                    datetime.fromisoformat(config["last_attempt_at"])
                    if config and config["last_attempt_at"] else None
                )
                if last_attempt is not None and last_attempt.tzinfo is None:
                    continue
            except Exception:
                continue
            if config is None or (
                last_attempt is not None and now - last_attempt < timedelta(hours=24)
            ):
                continue
            try:
                self.repository.record_auto_refresh_attempt(
                    profile.profile_id, profile.generation, now
                )
                cancel = self.lifecycle.register_task(profile.profile_id, profile.generation)
            except Exception:
                continue
            selection = PublicProfileSelection(
                uid=config["uid"], server_label=profile.server_label,
                provider_id=profile.provider_id, confirmed_by_user=True,
            )
            self._begin_profile_fetch(profile, selection, cancel, automatic=True)
            return

    def _reload_equipment(self) -> None:
        self.equipment_list.clear()
        profile = self._selected_profile()
        if profile is None:
            self.equipment_list.addItem("选择已有档案查看装备实例", None)
            self.confirm_equipment_button.setEnabled(False)
            self.equipment_link_target.clear()
            self.equipment_link_target.addItem("先选择待合并记录", None)
            self.link_equipment_button.setEnabled(False)
            return
        try:
            snapshot = self.repository.load_snapshot(profile.profile_id, profile.generation)
        except FileNotFoundError:
            snapshot = None
        except Exception as exc:
            self.equipment_list.addItem(f"无法读取档案：{exc}", None)
            self.confirm_equipment_button.setEnabled(False)
            self.equipment_link_target.clear()
            self.equipment_link_target.addItem("装备资料不可用", None)
            self.link_equipment_button.setEnabled(False)
            return
        if snapshot is None or not snapshot.equipment:
            self.equipment_list.addItem("此档案没有已导入的装备实例", None)
            self.confirm_equipment_button.setEnabled(False)
            self.equipment_link_target.clear()
            self.equipment_link_target.addItem("没有可合并记录", None)
            self.link_equipment_button.setEnabled(False)
            return
        for item in snapshot.equipment:
            owner = f"角色 {item.owner_character_id}" if item.owner_character_id else "未识别角色"
            identity = item.identity.value
            self.equipment_list.addItem(
                f"{item.slot} · 类型 {item.public_type_id} · {owner} · 身份 {identity}",
                (str(item.local_instance_id), identity, item.public_type_id, item.slot),
            )
        self._update_equipment_confirmation_enabled()
        self._reload_equipment_link_targets()

    def _update_equipment_confirmation_enabled(self, *_args: object) -> None:
        selected = self.equipment_list.currentData()
        self.confirm_equipment_button.setEnabled(
            selected is not None
            and selected[1] not in {
                EquipmentIdentity.SOURCE_CONFIRMED.value,
                EquipmentIdentity.PLAYER_CONFIRMED.value,
            }
        )

    def _reload_equipment_link_targets(self, *_args: object) -> None:
        self.equipment_link_target.clear()
        selected = self.equipment_list.currentData()
        profile = self._selected_profile()
        if selected is None or profile is None:
            self.equipment_link_target.addItem("先选择待合并记录", None)
            self.link_equipment_button.setEnabled(False)
            return
        try:
            snapshot = self.repository.load_snapshot(profile.profile_id, profile.generation)
        except Exception:
            snapshot = None
            self.equipment_link_target.addItem("装备目标不可用；请刷新档案列表", None)
            self.link_equipment_button.setEnabled(False)
            return
        candidates = tuple(
            item for item in snapshot.equipment
            if str(item.local_instance_id) != selected[0]
            and item.public_type_id == selected[2]
            and item.slot == selected[3]
        )
        for item in candidates:
            owner = f"角色 {item.owner_character_id}" if item.owner_character_id else "未识别角色"
            self.equipment_link_target.addItem(
                f"{item.slot} · {owner} · 身份 {item.identity.value}",
                str(item.local_instance_id),
            )
        if not candidates:
            self.equipment_link_target.addItem("没有相同类型和槽位的其他记录", None)
        self._update_equipment_link_enabled()

    def _update_equipment_link_enabled(self, *_args: object) -> None:
        selected = self.equipment_list.currentData()
        target_id = self.equipment_link_target.currentData()
        self.link_equipment_button.setEnabled(
            selected is not None and target_id is not None and selected[0] != target_id
        )

    def confirm_equipment_identity(self) -> None:
        profile = self._selected_profile()
        selection = self.equipment_list.currentData()
        if profile is None or selection is None:
            return
        answer = QMessageBox.question(
            self,
            "确认装备实例身份",
            "请确认所选记录对应玩家存档中的这个具体装备实例。确认后，规划器可将它作为可调配装备；"
            "仅类型相同或出现在公开展示页，不足以确认是同一件装备。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repository.confirm_equipment_instance(
                profile.profile_id, profile.generation, UUID(selection[0])
            )
        except Exception as exc:
            QMessageBox.warning(self, "装备身份未保存", str(exc))
            return
        self._reload_equipment()
        self.preview.setPlainText("玩家已逐件确认装备实例身份；确认结果已加密保存到当前档案。")

    def link_equipment_identity(self) -> None:
        profile = self._selected_profile()
        selected = self.equipment_list.currentData()
        existing_id = self.equipment_link_target.currentData()
        if profile is None or selected is None or existing_id is None:
            return
        answer = QMessageBox.question(
            self,
            "确认这是同一件装备",
            f"请确认所选记录与目标记录对应玩家存档中的同一件实体装备。"
            f"两者的公共类型相同（{selected[2]}）并不足以证明身份相同。\n\n"
            "确认后会保留目标记录的本地身份，并移除所选重复记录。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        link_args = {
            "profile_id": profile.profile_id,
            "generation": profile.generation,
            "imported_instance_id": UUID(selected[0]),
            "existing_instance_id": UUID(existing_id),
            "player_confirmed_same_copy": True,
        }
        try:
            try:
                self.repository.link_equipment_instances(**link_args)
            except EquipmentMergeConflictError as conflict_error:
                choices: dict[str, str] = {}
                for conflict in conflict_error.conflicts:
                    old_value = getattr(conflict.existing, "value", conflict.existing)
                    new_value = getattr(conflict.incoming, "value", conflict.incoming)
                    choice = QMessageBox.question(
                        self,
                        "装备字段来源冲突",
                        f"{conflict.path}\n\n已有记录：{old_value!r}\n导入记录：{new_value!r}\n\n"
                        "是：采用导入记录；否：保留已有记录；取消：停止合并。",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                        QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Cancel,
                    )
                    if choice == QMessageBox.StandardButton.Cancel:
                        return
                    choices[conflict.path] = (
                        "incoming" if choice == QMessageBox.StandardButton.Yes else "existing"
                    )
                self.repository.link_equipment_instances(**link_args, conflict_choices=choices)
        except Exception as exc:
            QMessageBox.warning(self, "装备记录未合并", str(exc))
            return
        self._reload_equipment()
        self.preview.setPlainText(
            "玩家确认的重复装备记录已合并；冲突字段按逐项选择的来源保存。"
        )

    def fetch_public(self) -> None:
        if not self.confirm_consent.isChecked():
            QMessageBox.warning(self, "需要明确授权", "先确认 UID、区服、服务商、用途和撤权方式。")
            return
        selection = PublicProfileSelection(
            uid=self.uid.text().strip(),
            server_label=self.server.text().strip(),
            provider_id=MihomoPublicProfileClient.PROVIDER_ID,
            confirmed_by_user=True,
        )
        selected_profile = self._selected_profile()
        if selected_profile:
            if selected_profile.provider_id != selection.provider_id:
                QMessageBox.warning(self, "来源不匹配", "当前选择档案的授权来源与 Mihomo 不同。")
                return
            if selected_profile.server_label != selection.server_label:
                QMessageBox.warning(self, "区服不匹配", "请使用当前档案已授权的区服，或新建独立档案。")
                return
            try:
                refresh_config = self.repository.auto_refresh_config(
                    selected_profile.profile_id, selected_profile.generation
                )
            except Exception:
                refresh_config = None
            if refresh_config and refresh_config["uid"] != selection.uid:
                QMessageBox.warning(
                    self, "UID 不匹配", "自动刷新已绑定另一 UID；请为不同 UID 创建独立档案。"
                )
                return
            profile = selected_profile
        else:
            if not self.label.text().strip():
                QMessageBox.warning(self, "需要档案名称", "请填写档案名称。")
                return
            profile = self.repository.begin_profile(
                label=self.label.text(), provider_id=selection.provider_id,
                server_label=selection.server_label,
            )
            self._reload_profiles()
            self.profile_list.setCurrentIndex(self.profile_list.findData(str(profile.profile_id)))
            self.uid.setText(selection.uid)
        try:
            cancel = self.lifecycle.register_task(profile.profile_id, profile.generation)
        except Exception as exc:
            self.preview.setPlainText(str(exc))
            return
        self._begin_profile_fetch(profile, selection, cancel, automatic=False)

    def _begin_profile_fetch(
        self,
        profile: ProfileSummary,
        selection: PublicProfileSelection,
        cancel: Any,
        *,
        automatic: bool,
    ) -> None:
        self.pending_profile = profile
        self.fetch_profile = profile
        self.pending = None
        self.pending_cancel = cancel
        self.pending_auto_refresh = automatic
        self.auto_refresh_running = automatic
        self.fetch_button.setEnabled(False)
        self.cancel_fetch_button.setEnabled(True)
        self.save_button.setEnabled(False)
        self.progress.setRange(0, 0)
        if automatic:
            self.preview.setPlainText("正在执行已单独授权的定时公开档案查询；UID 仅从加密配置读取。")
            self.progress_bus.updated.emit("自动刷新公开档案…", -1)
        else:
            self.preview.setPlainText("正在向 Mihomo 发送已确认的 UID 查询；UID 不写入应用日志或明文配置。")
            self.progress_bus.updated.emit("读取已授权的公开档案…", -1)
        worker = _ProfileFetchWorker(MihomoPublicProfileClient(), selection, cancel)
        worker.signals.completed.connect(self._fetch_completed)
        worker.signals.failed.connect(self._fetch_failed)
        worker.signals.cancelled.connect(self._fetch_cancelled)
        self.thread_pool.start(worker)
        self.confirm_consent.setChecked(False)

    def cancel_public_fetch(self) -> None:
        cancel = self.pending_cancel
        if cancel is None:
            return
        cancel.set()
        self.cancel_fetch_button.setEnabled(False)
        self.preview.setPlainText(
            "已请求取消读取。若 HTTP 请求已经发出，公开服务仍可能完成处理；"
            "本机会丢弃返回数据，不会创建导入预览。"
        )
        self.progress_bus.updated.emit("正在取消公开档案读取；返回数据将被丢弃。", -1)

    def _fetch_cancelled(self, cancel: object) -> None:
        if cancel is not self.pending_cancel:
            return
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.fetch_button.setEnabled(True)
        self.cancel_fetch_button.setEnabled(False)
        cancelled_profile = self.fetch_profile
        self.pending_cancel = None
        self.pending = None
        self.pending_profile = None
        self.fetch_profile = None
        self.pending_auto_refresh = False
        self.auto_refresh_running = False
        self.progress_bus.updated.emit("公开档案读取已取消；返回数据已丢弃。", 0)
        if cancelled_profile is not None:
            self.lifecycle.unregister_task(
                cancelled_profile.profile_id, cancelled_profile.generation, cancel
            )
        self.preview.setPlainText(
            "公开档案读取已取消。若请求已经发出，服务端仍可能完成处理；本机已丢弃其返回数据。"
        )

    def _fetch_completed(self, proposal: object, cancel: object) -> None:
        if cancel is not self.pending_cancel:
            return
        if cancel.is_set():
            self._fetch_cancelled(cancel)
            return
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.fetch_button.setEnabled(True)
        self.cancel_fetch_button.setEnabled(False)
        fetched_profile = self.fetch_profile
        completed_cancel = self.pending_cancel
        self.pending_cancel = None
        self.auto_refresh_running = False
        self.progress_bus.updated.emit("公开档案已到达本机，等待玩家确认导入。", 100)
        self.fetch_profile = None
        if fetched_profile is not None and completed_cancel is not None:
            self.lifecycle.unregister_task(
                fetched_profile.profile_id, fetched_profile.generation, completed_cancel
            )
        if not fetched_profile or not self.lifecycle.accepts_result(
            fetched_profile.profile_id, fetched_profile.generation
        ):
            self.pending = None
            self.preview.setPlainText("档案已撤权；异步返回结果已丢弃。")
            return
        if not isinstance(proposal, ImportProposal):
            self.preview.setPlainText("服务返回了不支持的预览对象。")
            return
        self.pending_profile = fetched_profile
        self.pending = proposal
        self._render_proposal(proposal)
        if self.pending_auto_refresh:
            self.preview.insertPlainText(
                "\n\n定时读取候选：自动刷新不会自动写入快照，请检查后点击“确认预览并保存”。"
            )
        self.pending_auto_refresh = False
        self.save_button.setEnabled(True)

    def _fetch_failed(self, message: str, cancel: object) -> None:
        if cancel is not self.pending_cancel:
            return
        if cancel.is_set():
            self._fetch_cancelled(cancel)
            return
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.fetch_button.setEnabled(True)
        self.cancel_fetch_button.setEnabled(False)
        failed_profile = self.fetch_profile
        failed_cancel = self.pending_cancel
        self.pending_cancel = None
        self.auto_refresh_running = False
        self.pending_auto_refresh = False
        self.progress_bus.updated.emit("公开档案读取失败；未导入数据。", 0)
        self.pending = None
        self.fetch_profile = None
        if failed_profile is not None and failed_cancel is not None:
            self.lifecycle.unregister_task(
                failed_profile.profile_id, failed_profile.generation, failed_cancel
            )
        if not failed_profile or not self.lifecycle.accepts_result(
            failed_profile.profile_id, failed_profile.generation
        ):
            self.preview.setPlainText("档案已撤权；异步失败结果已丢弃。")
            return
        self.preview.setPlainText(
            f"公开档案读取失败：{message}\n档案授权仍有效；若不再使用，请执行撤权并删除。"
        )

    def create_local(self) -> None:
        if not self.label.text().strip() or not self.server.text().strip():
            QMessageBox.information(self, "需要档案信息", "本地档案也需要名称和玩家选择的区服标签。")
            return
        profile = self.repository.begin_profile(
            label=self.label.text(), provider_id="local-import", server_label=self.server.text()
        )
        proposal = confirm_import(ManualImportAdapter().preview({}))
        self.repository.save_confirmed_import(profile.profile_id, profile.generation, proposal)
        self._reload_profiles()
        self.profile_list.setCurrentIndex(self.profile_list.findData(str(profile.profile_id)))
        self.preview.setPlainText("本地空档案已创建；可预览导入、逐字段确认后合并。")

    def preview_structured(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择本地结构化资料", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.pending = StructuredImportAdapter().preview_file(Path(path)).proposal
        except Exception as exc:
            self.pending = None
            self.preview.setPlainText(f"导入预览失败：{exc}")
            self.save_button.setEnabled(False)
            return
        self.pending_profile = self._selected_profile()
        self._render_proposal(self.pending)
        self.save_button.setEnabled(True)

    def preview_manual(self) -> None:
        path = self.manual_path.text().strip()
        if not path:
            QMessageBox.information(self, "需要字段路径", "填写要确认的本地字段路径。")
            return
        try:
            self.pending = ManualImportAdapter().preview({path: self.manual_value.text()})
        except Exception as exc:
            self.preview.setPlainText(f"手动字段预览失败：{exc}")
            self.save_button.setEnabled(False)
            return
        self.pending_profile = self._selected_profile()
        self._render_proposal(self.pending)
        self.save_button.setEnabled(True)

    def choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择截图", "", "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            try:
                image_bytes = read_ocr_image(Path(path))
            except OSError as exc:
                self.preview.setPlainText(f"无法读取所选截图：{type(exc).__name__}")
                return
            except ValueError as exc:
                self.preview.setPlainText(str(exc))
                return
            self._discard_ocr_preview()
            profile = self._selected_profile()
            cancel = threading.Event()
            if profile is not None:
                try:
                    cancel = self.lifecycle.register_task(profile.profile_id, profile.generation)
                except Exception as exc:
                    self.preview.setPlainText(f"档案已撤权，未开始 OCR：{exc}")
                    return
            self.ocr_profile = profile
            self.ocr_cancel = cancel
            worker = _OcrWorker(image_bytes, cancel)
            worker.signals.completed.connect(self._ocr_completed)
            worker.signals.failed.connect(self._ocr_failed)
            worker.signals.cancelled.connect(self._ocr_cancelled)
            self.progress.setRange(0, 0)
            self.progress_bus.updated.emit("本机 OCR 正在处理截图；图像未上传或复制。", -1)
            self.ocr_button.setEnabled(False)
            self.thread_pool.start(worker)

    def _ocr_completed(self, draft: object, cancel: threading.Event) -> None:
        if not self._finish_ocr_task(cancel):
            return
        profile = self.ocr_profile
        if cancel.is_set() or (
            profile is not None
            and (
                not self.lifecycle.accepts_result(profile.profile_id, profile.generation)
                or not self._same_profile_generation(profile, self._selected_profile())
            )
        ):
            self._discard_ocr_preview("档案已切换或撤权；OCR 异步结果已丢弃。")
            return
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress_bus.updated.emit("本机 OCR 完成；请把文本行映射到明确字段并核对。", 100)
        self.ocr_button.setEnabled(True)
        if not isinstance(draft, OcrDraft):
            self.ocr_profile = None
            self.ocr_draft = None
            self.ocr_candidate.clear()
            self.progress.setValue(0)
            self.progress_bus.updated.emit("OCR 未生成候选字段。", 0)
            self.preview.setPlainText("OCR 返回了不支持的结果；可改用手动或结构化导入。")
            return
        self.ocr_draft = draft
        self.ocr_candidate.clear()
        for index, line in enumerate(draft.lines):
            self.ocr_candidate.addItem(f"{index}: {line.text}  ({line.confidence:.0%})", index)
        if draft.lines:
            self.preview.setPlainText("\n".join(draft.warnings) + "\n\n选择识别行，填写字段路径，再映射后逐项确认。")
        else:
            self.preview.setPlainText("OCR 未识别出文本；原图未保存。可改用手动或结构化导入。")

    def _ocr_failed(self, message: str, cancel: threading.Event) -> None:
        if not self._finish_ocr_task(cancel):
            return
        profile = self.ocr_profile
        if cancel.is_set() or (
            profile is not None
            and (
                not self.lifecycle.accepts_result(profile.profile_id, profile.generation)
                or not self._same_profile_generation(profile, self._selected_profile())
            )
        ):
            self._discard_ocr_preview("档案已切换或撤权；OCR 异步结果已丢弃。")
            return
        self.ocr_profile = None
        self.ocr_draft = None
        self.ocr_candidate.clear()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress_bus.updated.emit("OCR 未生成候选字段。", 0)
        self.ocr_button.setEnabled(True)
        self.preview.setPlainText(f"本机 OCR 失败：{message}\n可改用手动或结构化导入。")

    def _ocr_cancelled(self, cancel: threading.Event) -> None:
        if not self._finish_ocr_task(cancel):
            return
        self._discard_ocr_preview("OCR 已取消，迟到的识别结果已丢弃。")

    def map_ocr_line(self) -> None:
        if self.ocr_draft is None or self.ocr_candidate.currentIndex() < 0:
            QMessageBox.information(self, "没有 OCR 文本", "先选择截图并等待本机 OCR 完成。")
            return
        field_path = self.manual_path.text().strip()
        line_index = self.ocr_candidate.currentData()
        try:
            self.pending = proposal_from_ocr_mapping(self.ocr_draft, {field_path: int(line_index)})
        except Exception as exc:
            QMessageBox.warning(self, "无法映射 OCR 行", str(exc))
            return
        self.pending_profile = self.ocr_profile or self._selected_profile()
        self._render_proposal(self.pending)
        self.save_button.setEnabled(True)

    def _render_proposal(self, proposal: ImportProposal) -> None:
        lines = ["预览候选（尚未写入）：", *proposal.warnings, "", "字段："]
        lines.extend(f"• {path} = {fact.value!r} [{fact.source_kind.value}; {fact.observed_at.isoformat()}]"
                     for path, fact in proposal.fields.items())
        lines.append("\n已确认拥有（仅当前展示名单）：" + ", ".join(proposal.ownership) )
        lines.append(f"设备候选：{len(proposal.equipment)} 件；实例身份需逐件确认。")
        self.preview.setPlainText("\n".join(lines))

    def save_preview(self) -> None:
        if self.pending is None:
            return
        proposal = confirm_import(self.pending)
        profile = self._selected_profile()
        if profile is None:
            QMessageBox.warning(self, "未选择档案", "请先创建本地档案或开始一个授权档案请求。")
            return
        try:
            if self.pending_profile and not self._same_profile_generation(
                self.pending_profile, profile
            ):
                raise ValueError("预览结果与当前档案不匹配")
            if self.pending_profile and not self.lifecycle.accepts_result(
                self.pending_profile.profile_id, self.pending_profile.generation
            ):
                raise PermissionError("预览所属档案授权已失效；请重新导入并预览。")
            merge_preview = self.repository.preview_merge(profile.profile_id, profile.generation, proposal)
            choices: dict[str, str] = {}
            for conflict in merge_preview.conflicts:
                answer = QMessageBox.question(
                    self,
                    "字段来源冲突",
                    f"{conflict.field_path}\n\n已有值：{conflict.existing.value!r}\n"
                    f"新值：{conflict.incoming.value!r}\n\n是：采用新值；否：保留已有值；取消：停止保存。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                    QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer == QMessageBox.StandardButton.Cancel:
                    return
                choices[conflict.field_path] = (
                    "incoming" if answer == QMessageBox.StandardButton.Yes else "existing"
                )
            result = self.repository.save_confirmed_import(
                profile.profile_id, profile.generation, proposal, conflict_choices=choices
            )
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.pending = None
        self.pending_profile = None
        self.save_button.setEnabled(False)
        self._reload_equipment()
        conflict_note = f" 已逐项处理 {len(result.conflicts)} 个冲突。" if result.conflicts else ""
        self.preview.setPlainText(
            "用户已确认预览；规范化字段已加密写入当前档案。" + conflict_note +
            "原始截图/导入文件未复制。"
        )

    def revoke_selected(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        answer = QMessageBox.question(
            self, "撤权并删除",
            "这会立即停止该档案分析、取消任务，并删除本地快照、私有配置、临时资料和关联报告。继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._discard_ocr_preview("档案撤权中，OCR 候选已清除。")
        try:
            if self.pending_cancel is not None and self.fetch_profile == profile:
                self.pending_cancel.set()
            self.repository.revoke(profile.profile_id)
        except Exception as exc:
            QMessageBox.critical(self, "撤权清理失败", f"档案已在当前进程停用，但持久清理失败：{exc}")
            return
        self.pending = None
        self.pending_profile = None
        self.fetch_profile = None
        self.pending_cancel = None
        self.pending_auto_refresh = False
        self.auto_refresh_running = False
        self.fetch_button.setEnabled(True)
        self.cancel_fetch_button.setEnabled(False)
        self._reload_profiles()
        self.preview.setPlainText("档案授权已撤销，关联本地资料已清理。")


class ReportsPage(_Page):
    def __init__(self, profiles: ProfileRepository, lifecycle: ProfileLifecycle,
                 store: EncryptedPrivateStore, public_cache: PublicBundleCache) -> None:
        super().__init__(
            "报告",
            "分析结果先在本机预览；只有用户主动保存后才加密留存。快照变化会使旧报告失效。",
        )
        self.profiles = profiles
        self.lifecycle = lifecycle
        self.public_cache = public_cache
        self.reports = ReportLifecycle(store, lifecycle)
        self.saved_reports: dict[str, AnalysisReport] = {}
        self.pending_report: AnalysisReport | None = None
        self.profile_list = QComboBox()
        self.refresh_button = QPushButton("刷新档案与报告状态")
        self.save_pending_button = QPushButton("主动保存当前分析结果")
        self.save_pending_button.setEnabled(False)
        self.status = QLabel("规划器尚未接入，不会自动生成或保存攻略报告。")
        self.status.setWordWrap(True)
        self.report_list = QListWidget()
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.content.addWidget(QLabel("本地档案"))
        row = QHBoxLayout()
        row.addWidget(self.profile_list, 1)
        row.addWidget(self.refresh_button)
        row.addWidget(self.save_pending_button)
        self.content.addLayout(row)
        self.content.addWidget(self.status)
        self.content.addWidget(self.report_list, 1)
        self.content.addWidget(self.detail, 2)
        self.refresh_button.clicked.connect(self.reload_profiles)
        self.save_pending_button.clicked.connect(self.save_pending_report)
        self.profile_list.currentIndexChanged.connect(self.refresh_reports)
        self.report_list.currentItemChanged.connect(self.show_report)
        self.reload_profiles()

    def reload_profiles(self) -> None:
        selected = self.profile_list.currentData()
        self.profile_list.clear()
        for profile in self.profiles.list_profiles():
            self.profile_list.addItem(profile.label, str(profile.profile_id))
        if selected is not None:
            index = self.profile_list.findData(selected)
            if index >= 0:
                self.profile_list.setCurrentIndex(index)
        self.refresh_reports()

    def showEvent(self, event: object) -> None:
        super().showEvent(event)
        self.reload_profiles()

    def refresh_reports(self, *_args: object) -> None:
        self.report_list.clear()
        self.saved_reports.clear()
        self.detail.clear()
        if self.pending_report is not None and not self.lifecycle.is_active(
            self.pending_report.profile_id, self.pending_report.authorization_generation
        ):
            self.pending_report = None
        selected = self.profile_list.currentData()
        self.save_pending_button.setEnabled(
            self.pending_report is not None
            and str(self.pending_report.profile_id) == selected
            and self.lifecycle.is_active(
                self.pending_report.profile_id, self.pending_report.authorization_generation
            )
        )
        profile = next((item for item in self.profiles.list_profiles()
                        if str(item.profile_id) == selected), None)
        if profile is None:
            self.status.setText("当前没有已授权档案。报告仅在用户主动保存后留存。")
            return
        try:
            snapshot = self.profiles.load_snapshot(profile.profile_id, profile.generation)
            revision: int | None = snapshot.revision
        except FileNotFoundError:
            revision = None
        try:
            reports = self.reports.list_saved(
                profile_id=profile.profile_id,
                generation=profile.generation,
                current_snapshot_revision=revision,
                current_public_release_id=self.public_cache.current_release_id(),
            )
        except Exception as exc:
            self.status.setText(f"无法读取报告：{exc}")
            return
        if not reports:
            self.status.setText(
                "没有已保存报告。生产分析尚待 M0 接通；TaskPage 的单独联调演示只使用合成 fixture。"
            )
            self._render_pending_report(selected)
            return
        self.status.setText(
            f"已加载 {len(reports)} 份用户主动保存的报告。本机缓存版本："
            f"{self.public_cache.current_release_id() or '未知'}；在线撤回状态未核实。"
        )
        labels = {
            "current": "当前",
            "needs_review": "需要核对",
            "expired": "快照已变化",
            "evidence_withdrawn": "证据已撤回",
        }
        for report in reports:
            report_key = str(report.report_id)
            self.saved_reports[report_key] = report
            demo_label = " · 仅合成 fixture" if report.task.get("synthetic_demo") is True else ""
            item = QListWidgetItem(
                f"{report.created_at.astimezone().strftime('%Y-%m-%d %H:%M')} · "
                f"{labels[report.validity.value]} · {report.planner_version}{demo_label}"
            )
            item.setData(Qt.ItemDataRole.UserRole, report_key)
            self.report_list.addItem(item)
        self._render_pending_report(selected)

    def show_report(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self.detail.clear()
            return
        report = self.saved_reports.get(str(current.data(Qt.ItemDataRole.UserRole)))
        if report is None:
            return
        self.detail.setPlainText(json.dumps({
            "状态": report.validity.value,
            "状态说明": report.validity_reason,
            "创建时间": report.created_at.isoformat(),
            "快照修订": report.snapshot_revision,
            "公共资料版本": report.public_release_id,
            "规划器版本": report.planner_version,
            "任务": report.task,
            "结果": report.result,
        }, ensure_ascii=False, indent=2))

    def stage_temporary_report(self, report: AnalysisReport) -> None:
        if not self.lifecycle.is_active(report.profile_id, report.authorization_generation):
            self.status.setText("分析结果所属档案已撤权；不能保存该结果。")
            return
        index = self.profile_list.findData(str(report.profile_id))
        if index < 0:
            self.reload_profiles()
            index = self.profile_list.findData(str(report.profile_id))
        if index < 0:
            self.status.setText("找不到分析结果所属档案；不能保存该结果。")
            return
        self.pending_report = report
        self.profile_list.setCurrentIndex(index)
        self.refresh_reports()

    def _render_pending_report(self, selected_profile_id: str | None) -> None:
        report = self.pending_report
        if report is None or str(report.profile_id) != selected_profile_id:
            return
        if not self.lifecycle.is_active(report.profile_id, report.authorization_generation):
            self.pending_report = None
            self.save_pending_button.setEnabled(False)
            self.status.setText("分析结果所属档案已撤权；待保存结果已丢弃。")
            return
        try:
            snapshot = self.profiles.load_snapshot(
                report.profile_id, report.authorization_generation
            )
            revision: int | None = snapshot.revision
        except FileNotFoundError:
            revision = None
        except PermissionError:
            self.pending_report = None
            self.save_pending_button.setEnabled(False)
            self.status.setText("分析结果所属档案已撤权；待保存结果已丢弃。")
            return
        try:
            report = self.reports.assess_for_display(
                report,
                current_snapshot_revision=revision,
                current_public_release_id=self.public_cache.current_release_id(),
            )
        except PermissionError:
            self.pending_report = None
            self.save_pending_button.setEnabled(False)
            self.status.setText("分析结果所属档案已撤权；待保存结果已丢弃。")
            return
        self.pending_report = report
        demo_label = "（仅合成 fixture，不代表真实游戏建议）" \
            if report.task.get("synthetic_demo") is True else ""
        validity_labels = {
            ReportValidity.CURRENT: "当前",
            ReportValidity.NEEDS_REVIEW: "需要核对",
            ReportValidity.EXPIRED: "快照已变化",
            ReportValidity.EVIDENCE_WITHDRAWN: "证据已撤回",
        }
        validity = validity_labels[report.validity]
        reason = report.validity_reason or "当前快照和公共资料版本与报告依据一致。"
        self.status.setText(
            f"有一份未保存的本地分析结果{demo_label}状态：{validity}。{reason} "
            "点击“主动保存当前分析结果”后才会加密留存。"
        )
        self.detail.setPlainText(json.dumps({
            "状态": report.validity.value,
            "状态说明": report.validity_reason,
            "快照修订": report.snapshot_revision,
            "公共资料版本": report.public_release_id,
            "规划器版本": report.planner_version,
            "任务": report.task,
            "结果": report.result,
        }, ensure_ascii=False, indent=2))

    def save_pending_report(self) -> None:
        report = self.pending_report
        if report is None:
            return
        if self.profile_list.currentData() != str(report.profile_id):
            self.status.setText("先切回此结果所属档案，再保存。")
            return
        try:
            try:
                snapshot = self.profiles.load_snapshot(
                    report.profile_id, report.authorization_generation
                )
                revision: int | None = snapshot.revision
            except FileNotFoundError:
                revision = None
            self.reports.save_explicitly(
                report,
                current_snapshot_revision=revision,
                current_public_release_id=self.public_cache.current_release_id(),
            )
        except Exception as exc:
            self.status.setText(f"报告未保存：{exc}")
            return
        self.pending_report = None
        self.reload_profiles()
        self.status.setText("分析结果已由用户主动确认并加密保存。")
        self.save_pending_button.setEnabled(False)


class PublicKnowledgePage(_Page):
    def __init__(self, cache: PublicBundleCache) -> None:
        super().__init__("公共资料", "公开知识缓存与私有账号档案分开保存。")
        self.cache = cache
        self.status = QTextEdit()
        self.status.setReadOnly(True)
        self.status.setAccessibleName("公共资料缓存与时效状态")
        self.content.addWidget(self.status)
        self.refresh_status()

    def refresh_status(self) -> None:
        current = self.cache.current_release_id()
        releases = self.cache.available_release_ids()
        lines = [
            f"当前缓存指针：{current or '无'}",
            f"本机缓存版本：{', '.join(releases) or '无'}",
            "本页离线状态：生产签名信任与 A 撤回清单尚待 M0；当前没有在线同步。",
            "本机最近撤回/禁用状态：未知（未取得在线确认或版本化撤回清单）。",
            "本机验签时间来自本地回执；回执未签名，仅与对应缓存字节摘要绑定。",
        ]
        for release_id in releases:
            role = "当前" if release_id == current else "保留旧版"
            lines.append(f"\n[{role}] {release_id}")
            try:
                metadata = self.cache.inspect_cached_metadata(release_id)
            except (OSError, ValueError, RecursionError) as exc:
                lines.append(f"  缓存元数据不可读：{exc}")
                lines.append("  该版本不得用于分析，直到同步器重新验证签名和成员依赖。")
                continue
            declared_id = metadata["declared_release_id"]
            lines.append(f"  包内 release 声明：{declared_id or '缺失'}")
            coverage = metadata["coverage"]
            coverage_text = (
                json.dumps(coverage, ensure_ascii=False, sort_keys=True, allow_nan=False)
                if coverage is not None else "未声明"
            )
            lines.append(f"  包内覆盖声明（未在本页验签）：{coverage_text[:1200]}")
            freshness = metadata["freshness"]
            freshness_text = (
                json.dumps(freshness, ensure_ascii=False, sort_keys=True, allow_nan=False)
                if freshness else "未声明"
            )
            lines.append(f"  包内时效声明（未在本页验签）：{freshness_text[:1200]}")
            receipt = metadata["verification_receipt"]
            receipt_status = receipt["status"]
            if receipt_status == "content-matched-local-record":
                lines.append(
                    f"  本机最近验签记录（未签名回执）：{receipt['verified_at']}；缓存摘要匹配。"
                )
            else:
                lines.append(f"  本机验签记录：{receipt_status}；不能确认最近验签时间。")
            lines.append(f"  本地缓存文件修改时间：{metadata['cache_file_modified_at']}")
        lines.extend((
            "",
            "本地验签回执不提供发布者真实性保证；包内覆盖/时效也不是当前有效性或撤回证明。",
            "分析前必须由配置了生产信任锚的同步器重新验证签名、成员哈希、能力和依赖。",
        ))
        self.status.setPlainText("\n".join(lines))


class SettingsPage(_Page):
    def __init__(self) -> None:
        super().__init__("设置与维护", "维护、审核、发布操作必须由服务身份授权并分别审计。")
        self.content.addWidget(QLabel(
            "本地服务生命周期与邀请服务维护接口尚未接通。当前没有管理凭据、自动更新或静默下载。"
        ))


class _ProgressPage(_Page):
    MAX_HISTORY = 50
    MODES = ("混沌回忆", "虚构叙事", "末日幻影")

    def __init__(self, profiles: ProfileRepository, progress_bus: _ProgressBus) -> None:
        super().__init__("进度", "查看当前档案的公开进度覆盖，以及本会话的后台任务状态。")
        self.profiles = profiles
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("本地档案"))
        self.profile_list = QComboBox()
        self.profile_list.setAccessibleName("进度页本地档案")
        self.refresh_profiles = QPushButton("刷新档案")
        profile_row.addWidget(self.profile_list, 1)
        profile_row.addWidget(self.refresh_profiles)
        self.content.addLayout(profile_row)
        self.mode_status = QTextEdit()
        self.mode_status.setReadOnly(True)
        self.mode_status.setAccessibleName("三种玩法进度覆盖")
        self.content.addWidget(self.mode_status)
        self.status = QLabel("当前没有后台任务。")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.content.addWidget(self.status)
        self.content.addWidget(self.bar)
        self.content.addWidget(QLabel("最近活动（仅保留在当前会话）"))
        self.history = QListWidget()
        self.history.setAccessibleName("最近进度活动")
        self.content.addWidget(self.history, 1)
        self.profile_list.currentIndexChanged.connect(self._refresh_mode_status)
        self.refresh_profiles.clicked.connect(self.reload_profiles)
        progress_bus.updated.connect(self._update)
        self.reload_profiles()

    def showEvent(self, event: object) -> None:
        super().showEvent(event)
        # Revocation on another page removes the profile from the repository. Refreshing
        # whenever this page becomes visible prevents stale private progress staying on screen.
        self.reload_profiles()

    def reload_profiles(self) -> None:
        selected = self.profile_list.currentData()
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for profile in self.profiles.list_profiles():
            self.profile_list.addItem(profile.label, str(profile.profile_id))
        index = self.profile_list.findData(selected)
        fallback = 0 if self.profile_list.count() else -1
        self.profile_list.setCurrentIndex(index if index >= 0 else fallback)
        self.profile_list.blockSignals(False)
        self._refresh_mode_status()

    def _refresh_mode_status(self, *_args: object) -> None:
        selected_id = self.profile_list.currentData()
        if not isinstance(selected_id, str):
            self.mode_status.setPlainText("尚无已授权档案。三种玩法的进度均为未知。")
            return
        profile = next(
            (item for item in self.profiles.list_profiles() if str(item.profile_id) == selected_id),
            None,
        )
        if profile is None:
            self.mode_status.setPlainText("档案已撤权或不存在。三种玩法的进度均为未知。")
            return
        try:
            snapshot = self.profiles.load_snapshot(profile.profile_id, profile.generation)
        except FileNotFoundError:
            snapshot = None
        except Exception:
            self.mode_status.setPlainText("档案资料不可读取；未显示旧进度。")
            return

        lines = [f"档案：{profile.label}", "", "玩法记录覆盖："]
        lines.extend(f"- {mode}：未知（没有可核实的该模式记录）" for mode in self.MODES)
        lines.append("缺少公开记录不代表未通关；M0 模式、周期和关卡映射未冻结。")
        summary_fields = {
            path: fact for path, fact in (snapshot.fields.items() if snapshot else ())
            if path.startswith("progress:mihomo-memory-summary:")
            and fact.source_kind is SourceKind.PUBLIC_PROFILE
            and fact.source_id == MihomoPublicProfileClient.PROVIDER_ID
        }
        lines.extend(("", "Mihomo 忘却之庭摘要（保留来源字段名，不映射到上述模式）："))
        if summary_fields:
            for path, fact in sorted(summary_fields.items()):
                source_field = path.rsplit(":", 1)[-1]
                lines.append(
                    f"- memory_data.{source_field}: {fact.value!r} · "
                    f"{fact.status.value} · 观测于 {fact.observed_at.isoformat()}"
                )
        else:
            lines.append("- 此档案没有已导入的 Mihomo 进度摘要字段。")
        self.mode_status.setPlainText("\n".join(lines))

    def _update(self, message: str, value: int) -> None:
        self.status.setText(message)
        if value < 0:
            self.bar.setRange(0, 0)
            progress_text = "进行中"
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(value)
            progress_text = f"{value}%"
        timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
        self.history.insertItem(0, f"{timestamp} · {progress_text} · {message}")
        while self.history.count() > self.MAX_HISTORY:
            self.history.takeItem(self.history.count() - 1)


class StarHelpWindow(QMainWindow):
    def __init__(self, store: EncryptedPrivateStore, temp_root: Path,
                 public_cache: PublicBundleCache) -> None:
        super().__init__()
        self.setWindowTitle("StarHelp")
        self.resize(1180, 760)
        self.lifecycle = ProfileLifecycle(store, temp_root)
        self.profiles = ProfileRepository(store, self.lifecycle)
        self.progress_bus = _ProgressBus()
        self.tasks = TaskRepository(store, self.lifecycle)

        shell = QWidget()
        layout = QHBoxLayout(shell)
        self.navigation = QListWidget()
        self.navigation.addItems(["任务", "公共资料", "账号与导入", "进度", "报告", "设置与维护"])
        self.navigation.setFixedWidth(180)
        self.pages = QStackedWidget()
        self.task_page = TaskPage(
            self.profiles, self.tasks, self.progress_bus, self.lifecycle, store
        )
        self.accounts_page = AccountsPage(self.profiles, self.lifecycle, self.progress_bus)
        self.progress_page = _ProgressPage(self.profiles, self.progress_bus)
        self.pages.addWidget(self.task_page)
        self.pages.addWidget(PublicKnowledgePage(public_cache))
        self.pages.addWidget(self.accounts_page)
        self.pages.addWidget(self.progress_page)
        self.reports_page = ReportsPage(self.profiles, self.lifecycle, store, public_cache)
        self.task_page.temporary_report_ready.connect(self.reports_page.stage_temporary_report)
        self.pages.addWidget(self.reports_page)
        self.pages.addWidget(SettingsPage())
        layout.addWidget(self.navigation)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(shell)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)


def create_window() -> StarHelpWindow:
    if os.name != "nt":
        raise OSError("StarHelp desktop private account storage requires Windows")
    local = Path(os.environ["LOCALAPPDATA"]) / "StarHelp"
    store = EncryptedPrivateStore.for_current_user()
    temp = local / "temp"
    cache = PublicBundleCache(local / "public-cache")
    return StarHelpWindow(store, temp, cache)
