from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .bundles import PublicBundleCache
from .imports import (
    ManualImportAdapter,
    OcrDraft,
    RapidOcrEngine,
    StructuredImportAdapter,
    confirm_import,
    proposal_from_ocr_mapping,
)
from .lifecycle import ProfileLifecycle
from .models import ImportProposal
from .profiles import ProfileRepository, ProfileSummary
from .public_profile import MihomoPublicProfileClient, PublicProfileSelection
from .storage import EncryptedPrivateStore


class _Signals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _ProgressBus(QObject):
    updated = Signal(str, int)


class _ProfileFetchWorker(QRunnable):
    def __init__(self, client: MihomoPublicProfileClient, selection: PublicProfileSelection,
                 cancelled: Any) -> None:
        super().__init__()
        self.client = client
        self.selection = selection
        self.cancelled = cancelled
        self.signals = _Signals()

    def run(self) -> None:
        if self.cancelled.is_set():
            return
        try:
            proposal = self.client.fetch(self.selection)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        if self.cancelled.is_set():
            return
        self.signals.completed.emit(proposal)


class _OcrWorker(QRunnable):
    def __init__(self, image_bytes: bytes) -> None:
        super().__init__()
        self.image_bytes = image_bytes
        self.signals = _Signals()

    def run(self) -> None:
        try:
            draft = RapidOcrEngine().recognize(self.image_bytes)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.completed.emit(draft)
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
    def __init__(self, profiles: ProfileRepository, progress_bus: _ProgressBus) -> None:
        super().__init__("任务", "选择公开关卡和本地档案。规划器尚未连接时不会生成模拟推荐。")
        self.profiles = profiles
        self.progress_bus = progress_bus
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
        self.locked.setPlaceholderText("本地装备实例 ID；未知身份不会参与调装")
        for label, widget in (("玩法", self.mode), ("周期", self.cycle), ("关卡", self.stage),
                              ("目标", self.goal), ("本地档案", self.profile),
                              ("固定角色", self.fixed), ("排除角色", self.excluded),
                              ("锁定装备", self.locked)):
            form.addRow(label, widget)
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
        row.addWidget(self.refresh_profiles)
        row.addWidget(self.analyze)
        self.content.addLayout(row)
        self.refresh_profiles.clicked.connect(self.reload_profiles)
        self.analyze.clicked.connect(self.create_task)
        self.reload_profiles()

    def reload_profiles(self) -> None:
        selected = self.profile.currentData()
        self.profile.clear()
        for profile in self.profiles.list_profiles():
            self.profile.addItem(profile.label, str(profile.profile_id))
        index = self.profile.findData(selected)
        if index >= 0:
            self.profile.setCurrentIndex(index)

    def create_task(self) -> None:
        if not self.cycle.text().strip() or not self.stage.text().strip():
            QMessageBox.information(self, "需要关卡范围", "请填写已核实的周期和关卡标识。")
            return
        if self.profile.currentIndex() < 0:
            QMessageBox.information(self, "需要本地档案", "请先创建并授权一个本地档案。")
            return
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status.setText(
            "任务已构建，但本地规划组件尚未接入。未发送账号字段，也未生成推荐；请等待明确版本的规划器产物。"
        )
        self.progress_bus.updated.emit("分析任务等待本地规划器接入；没有生成推荐。", 0)


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
        self.pending_cancel: Any = None
        self.ocr_draft: OcrDraft | None = None
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.profile_list = QComboBox()
        self.label = QLineEdit()
        self.label.setPlaceholderText("本地档案名称")
        self.uid = QLineEdit()
        self.uid.setPlaceholderText("仅用于本次已确认的公开查询，不会保存")
        self.server = QLineEdit()
        self.server.setPlaceholderText("明确选择/填写服务区；实际 UID 映射仍待 M0 核实")
        self.confirm_consent = QCheckBox(
            "我确认此 UID、区服、Mihomo 服务商和展示数据用途；服务仅收到 UID，"
            "区服字段留在本机且其服务端映射尚待核实。只读取公开展示档案，结果在本机预览，"
            "我可随时撤权并删除本档案资料。"
        )
        self.fetch_button = QPushButton("确认并读取公开档案")
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
        row = QHBoxLayout()
        for button in (self.fetch_button, self.local_button, self.import_button, self.manual_button,
                       self.ocr_button, self.map_ocr_button,
                       self.save_button, self.revoke_button):
            row.addWidget(button)
        self.content.addLayout(row)
        self.content.addWidget(self.ocr_candidate)
        self.content.addWidget(self.progress)
        self.content.addWidget(self.preview, 1)
        self.fetch_button.clicked.connect(self.fetch_public)
        self.local_button.clicked.connect(self.create_local)
        self.import_button.clicked.connect(self.preview_structured)
        self.manual_button.clicked.connect(self.preview_manual)
        self.ocr_button.clicked.connect(self.choose_image)
        self.map_ocr_button.clicked.connect(self.map_ocr_line)
        self.save_button.clicked.connect(self.save_preview)
        self.revoke_button.clicked.connect(self.revoke_selected)
        self.profile_list.currentIndexChanged.connect(self._selection_changed)
        self._reload_profiles()
        self._selection_changed()

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
        self.revoke_button.setEnabled(self._selected_profile() is not None)

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
        try:
            cancel = self.lifecycle.register_task(profile.profile_id, profile.generation)
        except Exception as exc:
            self.preview.setPlainText(str(exc))
            return
        self.pending_profile = profile
        self.pending = None
        self.pending_cancel = cancel
        self.fetch_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.preview.setPlainText("正在向 Mihomo 发送已确认的 UID 查询；UID 不写入应用日志或本地档案。")
        self.progress_bus.updated.emit("读取已授权的公开档案…", -1)
        worker = _ProfileFetchWorker(MihomoPublicProfileClient(), selection, cancel)
        worker.signals.completed.connect(self._fetch_completed)
        worker.signals.failed.connect(self._fetch_failed)
        self.thread_pool.start(worker)
        self.confirm_consent.setChecked(False)

    def _fetch_completed(self, proposal: object) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.fetch_button.setEnabled(True)
        self.pending_cancel = None
        self.progress_bus.updated.emit("公开档案已到达本机，等待玩家确认导入。", 100)
        if not self.pending_profile or not self.lifecycle.accepts_result(
            self.pending_profile.profile_id, self.pending_profile.generation
        ):
            self.pending = None
            self.preview.setPlainText("档案已撤权；异步返回结果已丢弃。")
            return
        if not isinstance(proposal, ImportProposal):
            self.preview.setPlainText("服务返回了不支持的预览对象。")
            return
        self.pending = proposal
        self._render_proposal(proposal)
        self.save_button.setEnabled(True)

    def _fetch_failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.fetch_button.setEnabled(True)
        self.pending_cancel = None
        self.progress_bus.updated.emit("公开档案读取失败；未导入数据。", 0)
        self.pending = None
        if not self.pending_profile or not self.lifecycle.accepts_result(
            self.pending_profile.profile_id, self.pending_profile.generation
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
                image_path = Path(path)
                if image_path.stat().st_size > RapidOcrEngine.MAX_IMAGE_BYTES:
                    raise ValueError("截图超过 16 MiB 本机 OCR 限制")
                image_bytes = image_path.read_bytes()
            except OSError as exc:
                self.preview.setPlainText(f"无法读取所选截图：{type(exc).__name__}")
                return
            except ValueError as exc:
                self.preview.setPlainText(str(exc))
                return
            worker = _OcrWorker(image_bytes)
            worker.signals.completed.connect(self._ocr_completed)
            worker.signals.failed.connect(self._ocr_failed)
            self.progress.setRange(0, 0)
            self.progress_bus.updated.emit("本机 OCR 正在处理截图；图像未上传或复制。", -1)
            self.ocr_button.setEnabled(False)
            self.thread_pool.start(worker)

    def _ocr_completed(self, draft: object) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress_bus.updated.emit("本机 OCR 完成；请把文本行映射到明确字段并核对。", 100)
        self.ocr_button.setEnabled(True)
        if not isinstance(draft, OcrDraft):
            self._ocr_failed("OCR 返回了不支持的结果")
            return
        self.ocr_draft = draft
        self.ocr_candidate.clear()
        for index, line in enumerate(draft.lines):
            self.ocr_candidate.addItem(f"{index}: {line.text}  ({line.confidence:.0%})", index)
        if draft.lines:
            self.preview.setPlainText("\n".join(draft.warnings) + "\n\n选择识别行，填写字段路径，再映射后逐项确认。")
        else:
            self.preview.setPlainText("OCR 未识别出文本；原图未保存。可改用手动或结构化导入。")

    def _ocr_failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress_bus.updated.emit("OCR 未生成候选字段。", 0)
        self.ocr_button.setEnabled(True)
        self.preview.setPlainText(f"本机 OCR 失败：{message}\n可改用手动或结构化导入。")

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
        self.pending_profile = self._selected_profile()
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
            if self.pending_profile and self.pending_profile.profile_id != profile.profile_id:
                raise ValueError("预览结果与当前档案不匹配")
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
        try:
            if self.pending_cancel is not None and self.pending_profile == profile:
                self.pending_cancel.set()
            self.repository.revoke(profile.profile_id)
        except Exception as exc:
            QMessageBox.critical(self, "撤权清理失败", f"档案已在当前进程停用，但持久清理失败：{exc}")
            return
        self.pending = None
        self.pending_profile = None
        self._reload_profiles()
        self.preview.setPlainText("档案授权已撤销，关联本地资料已清理。")


class ReportsPage(_Page):
    def __init__(self) -> None:
        super().__init__("报告", "报告仅在用户主动保存后以用户级加密形式留存。")
        self.content.addWidget(QLabel(
            "规划器尚未接入，本组件不会编造攻略报告。接入后将显示报告版本、过期与撤回状态。"
        ))


class PublicKnowledgePage(_Page):
    def __init__(self, cache: PublicBundleCache) -> None:
        super().__init__("公共资料", "公开知识缓存与私有账号档案分开保存。")
        self.cache = cache
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.content.addWidget(self.status)
        self.refresh_status()

    def refresh_status(self) -> None:
        self.status.setText(
            f"当前缓存版本：{self.cache.current_release_id() or '无'}\n"
            f"本机已验证包：{', '.join(self.cache.available_release_ids()) or '无'}\n"
            "签名公钥、生产包格式和发布方撤回清单尚待 M0/A 交付；未启用远端同步。"
        )


class SettingsPage(_Page):
    def __init__(self) -> None:
        super().__init__("设置与维护", "维护、审核、发布操作必须由服务身份授权并分别审计。")
        self.content.addWidget(QLabel(
            "本地服务生命周期与邀请服务维护接口尚未接通。当前没有管理凭据、自动更新或静默下载。"
        ))


class _ProgressPage(_Page):
    def __init__(self, progress_bus: _ProgressBus) -> None:
        super().__init__("进度", "耗时任务在后台运行；撤权会取消任务并拒收迟到结果。")
        self.status = QLabel("当前没有后台任务。")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.content.addWidget(self.status)
        self.content.addWidget(self.bar)
        progress_bus.updated.connect(self._update)

    def _update(self, message: str, value: int) -> None:
        self.status.setText(message)
        if value < 0:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(value)


class StarHelpWindow(QMainWindow):
    def __init__(self, store: EncryptedPrivateStore, temp_root: Path,
                 public_cache: PublicBundleCache) -> None:
        super().__init__()
        self.setWindowTitle("StarHelp")
        self.resize(1180, 760)
        self.lifecycle = ProfileLifecycle(store, temp_root)
        self.profiles = ProfileRepository(store, self.lifecycle)
        self.progress_bus = _ProgressBus()

        shell = QWidget()
        layout = QHBoxLayout(shell)
        self.navigation = QListWidget()
        self.navigation.addItems(["任务", "公共资料", "账号与导入", "进度", "报告", "设置与维护"])
        self.navigation.setFixedWidth(180)
        self.pages = QStackedWidget()
        self.task_page = TaskPage(self.profiles, self.progress_bus)
        self.accounts_page = AccountsPage(self.profiles, self.lifecycle, self.progress_bus)
        self.progress_page = _ProgressPage(self.progress_bus)
        self.pages.addWidget(self.task_page)
        self.pages.addWidget(PublicKnowledgePage(public_cache))
        self.pages.addWidget(self.accounts_page)
        self.pages.addWidget(self.progress_page)
        self.pages.addWidget(ReportsPage())
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
