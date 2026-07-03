// 画布画笔/文字/撤销重做管理器。
// 与 DOM 控件解耦：工具状态变化、历史可用性、文字配置全部经 PaintHost 回调与 React 同步。

import { appAlert } from '../dialog';

export type PaintTool = 'brush' | 'eraser' | 'text' | null;

interface TextElement {
  text: string;
  x: number;
  y: number;
  font: string;
  color: string;
}

type LineSegment =
  | { type: 'dot'; x: number; y: number; color: string; size: number }
  | { type: 'line'; x1: number; y1: number; x2: number; y2: number; color: string; size: number };

interface CanvasState {
  // 整张位图快照：仅"全量"步保留（空白基线/抖动烘焙/旋转等无法由笔迹重建的画面）。
  // 笔迹/文字这类"增量"步不存位图（imageData 为 undefined），靠回放 lineSegments/textElements 重建，
  // 从而省掉大画布下每存一次的整张 getImageData 同步分配（逐笔卡顿根因）。
  imageData?: ImageData;
  textElements: TextElement[];
  lineSegments: LineSegment[];
  // 上面两个数组克隆的估算字节（按 JSON 字符串长度），保存时算好缓存在这，
  // 供 enforceHistoryBudget 计入内存预算，免得每次淘汰检查都重新 stringify 全栈
  elementsBytes: number;
}

export interface PaintHost {
  setCanvasTitle: (title: string) => void;
  onToolChange: (tool: PaintTool) => void;
  onHistoryChange: (canUndo: boolean, canRedo: boolean) => void;
  // 放置文字时读取当前输入内容与字体设置
  getTextConfig: () => { text: string; fontFamily: string; fontSize: number };
  onTextPlaced: () => void;
}

export class PaintManager {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private host: PaintHost;

  private painting = false;
  private lastX = 0;
  private lastY = 0;
  brushColor = '#000000';
  brushSize = 2;
  currentTool: PaintTool = null;
  private textElements: TextElement[] = [];
  private lineSegments: LineSegment[] = [];
  private isTextPlacementMode = false;
  private draggingCanvasContext: ImageData | null = null;
  private selectedTextElement: TextElement | null = null;
  private isDraggingText = false;
  private dragOffsetX = 0;
  private dragOffsetY = 0;
  textBold = false;
  textItalic = false;

  // Brush cursor indicator
  private brushCursor: HTMLDivElement | null = null;
  private cursorUpdateScheduled = false;
  private pendingCursorX = 0;
  private pendingCursorY = 0;

  // Undo/Redo functionality
  private historyStack: CanvasState[] = [];
  private historyStep = -1;
  private readonly MAX_HISTORY = 50;
  // 历史快照总字节上限（约 64MB），据此淘汰最旧全量快照，避免大画布满栈位图常驻撑爆内存
  private readonly MAX_HISTORY_BYTES = 64 * 1024 * 1024;
  // 增量步连续累计到该步数时强制补一张全量位图基线，原因有二：
  //   1) 撤销到很旧的增量步时回放笔迹数有上限，避免一次重建画太多线段；
  //   2) 让全量基线均匀散布在栈中，淘汰最旧步时不会因唯一基线被删而整栈坍塌（撤销深度骤降）。
  // 取 16：单张位图基线最坏占 ~2.6MB，预算 64MB 仍可容纳约 24 张基线，远超常见撤销深度。
  private readonly REBASELINE_INTERVAL = 16;

  constructor(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D, host: PaintHost) {
    this.canvas = canvas;
    this.ctx = ctx;
    this.host = host;

    this.startPaint = this.startPaint.bind(this);
    this.paint = this.paint.bind(this);
    this.endPaint = this.endPaint.bind(this);
    this.handleCanvasClick = this.handleCanvasClick.bind(this);
    this.onTouchStart = this.onTouchStart.bind(this);
    this.onTouchMove = this.onTouchMove.bind(this);
    this.onTouchEnd = this.onTouchEnd.bind(this);
    this.handleKeyboard = this.handleKeyboard.bind(this);
    this.updateBrushCursor = this.updateBrushCursor.bind(this);
    this.hideBrushCursor = this.hideBrushCursor.bind(this);
  }

  // 历史保存分两种"步"，对应审计 E16 列出的两个独立危害：
  //
  // 1) 内存膨胀（已修）：满栈整张位图 ~124MB 常驻 → 由下方 MAX_HISTORY_BYTES 字节预算淘汰收敛。
  //
  // 2) 逐笔卡顿（本次补全）：大画布（1360×480≈2.6MB / 960×640≈2.4MB）下每存一步都做一次整张
  //    getImageData——这是跑在主线程的同步操作 + 一次大数组分配；连续描边时每个 endPaint 都触发，
  //    用户逐笔可感知卡顿，且字节预算只削减"保留的栈"、对"每存的同步分配成本"零作用。
  //    本质修复（采纳审计建议"改存增量，lineSegments/textElements 可重建"）：
  //      - 仅"追加型"改动（endPaint 描边追加 lineSegments / placeText 追加 textElements）存为"增量"步
  //        （显式传 reconstructable=true），完全不调用 getImageData、不分配整张位图，彻底消除大画布逐笔
  //        的主线程像素拷贝成本；增量步回放时按基线时的数组长度切片只补"新增"部分（见 restoreFromHistory）。
  //      - 画面无法由笔迹重建时（空白基线 / 抖动烘焙 / 旋转后的烘焙位图），以及"就地修改"型改动
  //        （dragText 改写已存在文字的 x/y，非追加，切片回放无法体现位移）存"全量"位图快照（默认）。
  //    撤销/重做时增量步从其前方最近的全量位图回放新增笔迹重建，恢复结果与原整张快照一致。
  //
  // 参数：
  //   reconstructable=false（默认）→ 全量步，存整张位图。默认保守取全量，是为了让外部调用方
  //                                 （Epaper.tsx 的 convertDithering 抖动烘焙 / rotate 旋转 / clearCanvas
  //                                 清屏）无需改动即保持正确语义——这些画面都无法由笔迹重建，必须全量。
  //   reconstructable=true        → 增量步，不存位图。仅本类内部可由笔迹/文字完整重建的保存点显式传入
  //                                 （endPaint 描边 / placeText 放字），以消除大画布逐笔 getImageData 卡顿。
  //   snapshot                    → 仅全量步生效：调用方若已持有最终像素副本可传入复用，省掉一次
  //                                 重复 getImageData（如 convertDithering 写回画布后本就持有副本）。
  //                                 约定：传入的 snapshot 必须是调用方拥有、之后不会再 mutate/transfer
  //                                 其 buffer 的副本，否则历史快照会被破坏（勿传将转移到 worker 的 buffer）。
  saveToHistory(snapshot?: ImageData, reconstructable: boolean = false) {
    // 撤销后再绘制时丢弃后续历史
    this.historyStack = this.historyStack.slice(0, this.historyStep + 1);

    // 统计自最近一张全量位图以来已累计的连续增量步数；同时判断是否存在可作回放基线的全量位图。
    let incrementalRun = 0;
    let hasBaseline = false;
    for (let i = this.historyStep; i >= 0; i--) {
      if (this.historyStack[i].imageData != null) { hasBaseline = true; break; }
      incrementalRun++;
    }

    // 决定本步存全量还是增量：
    //   - 调用方声明不可重建（抖动/旋转等烘焙画面）→ 必存全量；
    //   - 尚无任何基线（理论上 attach() 已铺，此处为防御）→ 必存全量保证可恢复；
    //   - 连续增量步达到 REBASELINE_INTERVAL → 补一张全量基线（见常量说明），其余情况存增量。
    const storeFull = !reconstructable || !hasBaseline || incrementalRun >= this.REBASELINE_INTERVAL;

    // 克隆拆成"先 stringify 再 parse"两步，顺手拿字符串长度估算这两个数组占的内存，计入历史预算
    const textJson = JSON.stringify(this.textElements);
    const lineJson = JSON.stringify(this.lineSegments);
    const canvasState: CanvasState = {
      imageData: storeFull
        ? (snapshot ?? this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height))
        : undefined,
      textElements: JSON.parse(textJson),
      lineSegments: JSON.parse(lineJson),
      elementsBytes: textJson.length + lineJson.length,
    };

    this.historyStack.push(canvasState);
    this.historyStep++;

    this.enforceHistoryBudget();
    this.notifyHistoryChange();
  }

  // 淘汰最旧历史以同时满足两条约束（对应 E16 的两个危害维度）：
  //   ① 内存：按实际保留字节数 ≤ MAX_HISTORY_BYTES 收敛——"全量"步的整张位图 + 每步笔迹/文字
  //      数组克隆的估算字节（笔迹上千时 50 步各持一份克隆也会累积到数十 MB，不能只算位图），
  //      避免满栈快照常驻撑爆 renderer 内存；
  //   ② 步数：总步数 ≤ MAX_HISTORY，保持撤销深度上限语义与原一致。
  // 与旧版"按单张字节数推算固定步数上限"相比，这里按真实保留字节计：增量步多时撤销深度不再被
  // 误压到 ~24 步，仍严守 64MB 内存红线。
  private enforceHistoryBudget() {
    const retainedBytes = () => this.historyStack.reduce(
      (sum, s) => sum + (s.imageData ? s.imageData.data.byteLength : 0) + s.elementsBytes,
      0,
    );

    // 超出步数上限或位图字节预算时，从最旧端淘汰（一次可能淘汰多步）
    while (
      this.historyStack.length > 0 &&
      (this.historyStack.length > this.MAX_HISTORY || retainedBytes() > this.MAX_HISTORY_BYTES)
    ) {
      this.historyStack.shift();
      this.historyStep--;

      // 淘汰一个全量步后，紧随其后的"增量"步会失去回放基线（无法再重建），一并丢弃，
      // 保证栈底始终是一个可作基线的全量位图，避免撤销到无基线的步导致画面错乱。
      while (this.historyStack.length > 0 && this.historyStack[0].imageData == null) {
        this.historyStack.shift();
        this.historyStep--;
      }
    }

    if (this.historyStep < 0 && this.historyStack.length > 0) {
      // 边界保护：步指针被淘汰到负值但栈非空时，归位到栈底
      this.historyStep = 0;
    }
  }

  clearHistory() {
    this.historyStack = [];
    this.historyStep = -1;
    this.notifyHistoryChange();
  }

  undo() {
    if (this.historyStep > 0) {
      this.historyStep--;
      this.restoreFromHistory();
    }
  }

  redo() {
    if (this.historyStep < this.historyStack.length - 1) {
      this.historyStep++;
      this.restoreFromHistory();
    }
  }

  private restoreFromHistory() {
    if (this.historyStep >= 0 && this.historyStep < this.historyStack.length) {
      const state = this.historyStack[this.historyStep];
      this.textElements = JSON.parse(JSON.stringify(state.textElements));
      this.lineSegments = JSON.parse(JSON.stringify(state.lineSegments));

      if (state.imageData != null) {
        // 全量步：直接回放整张位图（与原行为一致）
        this.ctx.putImageData(state.imageData, 0, 0);
      } else {
        // 增量步：向前找最近的全量位图作基线 putImageData，再回放该基线之后新增的笔迹/文字重建画面。
        // 只回放"新增"部分（基线已把更早的笔迹烘焙进位图，重复回放会双画），故按基线时的数组长度切片。
        let baseIdx = this.historyStep;
        while (baseIdx >= 0 && this.historyStack[baseIdx].imageData == null) baseIdx--;

        const base = baseIdx >= 0 ? this.historyStack[baseIdx] : null;
        if (base?.imageData != null) {
          this.ctx.putImageData(base.imageData, 0, 0);
        }
        const baseLineCount = base ? base.lineSegments.length : 0;
        const baseTextCount = base ? base.textElements.length : 0;
        this.replaySegments(state.lineSegments.slice(baseLineCount));
        this.replayTextElements(state.textElements.slice(baseTextCount));
      }

      // 上面整体换掉了 textElements（全是新克隆对象），选中/拖动态里存的还是换掉前的旧引用：
      // 留着会让 startPaint 的 === 命中判定永远失败（拖动静默失效），旧画面快照也一直占内存。
      // 这里一并清掉，口径与 cancelTextPlacement 一致。
      this.selectedTextElement = null;
      this.draggingCanvasContext = null;
      this.isDraggingText = false;

      this.notifyHistoryChange();
    }
  }

  // 回放指定笔迹（增量步重建用）。与 redrawLineSegments 逻辑一致，但只画传入的子集。
  private replaySegments(segments: LineSegment[]) {
    segments.forEach(segment => {
      this.ctx.lineJoin = 'round';
      this.ctx.lineCap = 'round';
      this.ctx.strokeStyle = segment.color;
      this.ctx.lineWidth = segment.size;
      this.ctx.beginPath();
      if (segment.type === 'dot') {
        this.ctx.moveTo(segment.x, segment.y);
        this.ctx.lineTo(segment.x + 0.1, segment.y + 0.1);
      } else {
        this.ctx.moveTo(segment.x1, segment.y1);
        this.ctx.lineTo(segment.x2, segment.y2);
      }
      this.ctx.stroke();
    });
  }

  // 回放指定文字（增量步重建用）。与 redrawTextElements 逻辑一致，但只画传入的子集。
  private replayTextElements(items: TextElement[]) {
    items.forEach(item => {
      this.ctx.font = item.font;
      this.ctx.fillStyle = item.color;
      this.ctx.fillText(item.text, item.x, item.y);
    });
  }

  private notifyHistoryChange() {
    this.host.onHistoryChange(
      this.historyStep > 0,
      this.historyStep < this.historyStack.length - 1,
    );
  }

  // 绑定画布与键盘事件（组件挂载时调用一次）
  attach() {
    this.canvas.addEventListener('mousedown', this.startPaint);
    this.canvas.addEventListener('mousemove', this.paint);
    this.canvas.addEventListener('mouseup', this.endPaint);
    this.canvas.addEventListener('mouseleave', this.endPaint);
    this.canvas.addEventListener('click', this.handleCanvasClick);

    // Touch support
    this.canvas.addEventListener('touchstart', this.onTouchStart);
    this.canvas.addEventListener('touchmove', this.onTouchMove);
    this.canvas.addEventListener('touchend', this.onTouchEnd);

    // Keyboard shortcuts for undo/redo
    document.addEventListener('keydown', this.handleKeyboard);

    // Mouse move for brush cursor
    this.canvas.addEventListener('mouseenter', this.updateBrushCursor);
    this.canvas.addEventListener('mousemove', this.updateBrushCursor);

    this.createBrushCursor();

    // 以空白画布初始化历史：基线无法由笔迹重建，必须存为全量位图快照（后续增量步的回放基线）
    this.saveToHistory(undefined, false);
  }

  // 解绑全部事件并移除画笔光标（组件卸载时调用）
  detach() {
    this.canvas.removeEventListener('mousedown', this.startPaint);
    this.canvas.removeEventListener('mousemove', this.paint);
    this.canvas.removeEventListener('mouseup', this.endPaint);
    this.canvas.removeEventListener('mouseleave', this.endPaint);
    this.canvas.removeEventListener('click', this.handleCanvasClick);
    this.canvas.removeEventListener('touchstart', this.onTouchStart);
    this.canvas.removeEventListener('touchmove', this.onTouchMove);
    this.canvas.removeEventListener('touchend', this.onTouchEnd);
    document.removeEventListener('keydown', this.handleKeyboard);
    this.canvas.removeEventListener('mouseenter', this.updateBrushCursor);
    this.canvas.removeEventListener('mousemove', this.updateBrushCursor);
    this.brushCursor?.remove();
    this.brushCursor = null;
  }

  private handleKeyboard(e: KeyboardEvent) {
    // 焦点在文本输入控件时不拦截，避免破坏原生撤销/重做与文本编辑
    const t = e.target as HTMLElement | null;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
      return;
    }

    // 按住 Shift 时 e.key 上报为大写，统一转小写比较
    const k = e.key.toLowerCase();

    // Ctrl+Z or Cmd+Z for undo
    if ((e.ctrlKey || e.metaKey) && k === 'z' && !e.shiftKey) {
      e.preventDefault();
      this.undo();
    }
    // Ctrl+Y or Ctrl+Shift+Z or Cmd+Shift+Z for redo
    else if ((e.ctrlKey || e.metaKey) && (k === 'y' || (e.shiftKey && k === 'z'))) {
      e.preventDefault();
      this.redo();
    }
  }

  setActiveTool(tool: PaintTool, title: string) {
    this.host.setCanvasTitle(title);
    this.currentTool = tool;
    this.host.onToolChange(tool);

    // 取消未完成的文字放置
    this.cancelTextPlacement();
  }

  private createBrushCursor() {
    this.brushCursor = document.createElement('div');
    this.brushCursor.id = 'brush-cursor';
    this.brushCursor.style.position = 'fixed';
    this.brushCursor.style.border = '2px solid rgba(0, 0, 0, 0.5)';
    this.brushCursor.style.borderRadius = '50%';
    this.brushCursor.style.pointerEvents = 'none';
    this.brushCursor.style.display = 'none';
    this.brushCursor.style.zIndex = '10000';
    this.brushCursor.style.transform = 'translate(-50%, -50%)';
    this.brushCursor.style.willChange = 'transform';
    this.brushCursor.style.left = '0';
    this.brushCursor.style.top = '0';
    document.body.appendChild(this.brushCursor);
    this.updateBrushCursorSize();

    this.cursorUpdateScheduled = false;
    this.pendingCursorX = 0;
    this.pendingCursorY = 0;
  }

  updateBrushCursorSize() {
    if (!this.brushCursor) return;

    const rect = this.canvas.getBoundingClientRect();
    const scaleX = rect.width / this.canvas.width;
    const scaleY = rect.height / this.canvas.height;
    const scale = Math.min(scaleX, scaleY);

    const size = this.brushSize * scale;
    this.brushCursor.style.width = size + 'px';
    this.brushCursor.style.height = size + 'px';
  }

  private updateBrushCursor(e: MouseEvent) {
    if (!this.brushCursor) return;

    if (this.currentTool === 'brush' || this.currentTool === 'eraser') {
      const rect = this.canvas.getBoundingClientRect();
      const isInCanvas = e.clientX >= rect.left &&
        e.clientX <= rect.right &&
        e.clientY >= rect.top &&
        e.clientY <= rect.bottom;

      if (isInCanvas) {
        this.brushCursor.style.display = 'block';
        this.canvas.style.cursor = 'none';

        this.pendingCursorX = e.clientX;
        this.pendingCursorY = e.clientY;

        // requestAnimationFrame 节流，保证拖动平滑
        if (!this.cursorUpdateScheduled) {
          this.cursorUpdateScheduled = true;
          requestAnimationFrame(() => {
            if (!this.brushCursor) return;
            this.brushCursor.style.transform = `translate(${this.pendingCursorX}px, ${this.pendingCursorY}px) translate(-50%, -50%)`;
            this.cursorUpdateScheduled = false;
          });
        }

        // 橡皮擦与画笔用不同的光标样式（仅在工具切换时更新一次）
        if (this.currentTool === 'eraser') {
          if (this.brushCursor.getAttribute('data-tool') !== 'eraser') {
            this.brushCursor.style.border = '2px solid rgba(255, 0, 0, 0.7)';
            this.brushCursor.style.backgroundColor = 'rgba(255, 255, 255, 0.2)';
            this.brushCursor.style.boxShadow = 'none';
            this.brushCursor.setAttribute('data-tool', 'eraser');
          }
        } else {
          if (this.brushCursor.getAttribute('data-tool') !== 'brush') {
            this.brushCursor.style.border = '1px solid white';
            this.brushCursor.style.boxShadow = '0 0 0 1px black, inset 0 0 0 1px black';
            this.brushCursor.style.backgroundColor = 'transparent';
            this.brushCursor.setAttribute('data-tool', 'brush');
          }
        }
      } else {
        this.brushCursor.style.display = 'none';
      }
    }
  }

  private hideBrushCursor() {
    if (this.brushCursor) {
      this.brushCursor.style.display = 'none';
    }
    this.canvas.style.cursor = 'default';
  }

  private startPaint(e: MouseEvent) {
    if (!this.currentTool) return;

    if (this.currentTool === 'text') {
      // 点中已选中的文字则进入拖动
      const textElement = this.findTextElementAt(e);
      if (textElement && textElement === this.selectedTextElement) {
        this.isDraggingText = true;

        const rect = this.canvas.getBoundingClientRect();
        const scaleX = this.canvas.width / rect.width;
        const scaleY = this.canvas.height / rect.height;
        const x = (e.clientX - rect.left) * scaleX;
        const y = (e.clientY - rect.top) * scaleY;

        this.dragOffsetX = textElement.x - x;
        this.dragOffsetY = textElement.y - y;

        return;
      }
    } else {
      this.painting = true;
      this.draw(e);
    }
  }

  private endPaint() {
    if (this.painting) {
      // 描边结束：lineSegments 仅追加（append-only），增量步回放 slice(baseLineCount) 的新增笔迹即可
      // 完整重建，故存增量步，不做整张 getImageData —— 这是消除大画布逐笔卡顿的关键路径。
      this.saveToHistory(undefined, true);
    } else if (this.isDraggingText) {
      // 文字拖动结束：dragText 是就地改写已存在文字的 x/y（非追加），增量步回放只画 slice(baseTextCount)
      // 的"新增"文字，无法体现这次就地位移；若该文字已被先前的全量基线烘焙在旧位置，撤销/重做会丢失
      // 拖动结果（审计 E16 上一轮重构引入的回归）。故文字拖动后存全量快照，与原整张快照语义一致。
      this.saveToHistory(undefined, false);
    }
    this.painting = false;
    this.isDraggingText = false;
    this.lastX = 0;
    this.lastY = 0;

    this.hideBrushCursor();
  }

  private paint(e: MouseEvent) {
    if (!this.currentTool) return;

    if (this.currentTool === 'text') {
      if (this.isDraggingText && this.selectedTextElement) {
        this.dragText(e);
      }
    } else {
      if (this.painting) {
        this.draw(e);
      }
    }
  }

  private draw(e: MouseEvent) {
    const rect = this.canvas.getBoundingClientRect();
    const scaleX = this.canvas.width / rect.width;
    const scaleY = this.canvas.height / rect.height;
    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;

    this.ctx.lineJoin = 'round';
    this.ctx.lineCap = 'round';
    this.ctx.strokeStyle = this.brushColor;
    this.ctx.lineWidth = this.brushSize;

    this.ctx.beginPath();

    if (this.lastX === 0 && this.lastY === 0) {
      // 起笔画一个点
      this.ctx.moveTo(x, y);
      this.ctx.lineTo(x + 0.1, y + 0.1);

      this.lineSegments.push({
        type: 'dot',
        x,
        y,
        color: this.brushColor,
        size: this.brushSize,
      });
    } else {
      this.ctx.moveTo(this.lastX, this.lastY);
      this.ctx.lineTo(x, y);

      this.lineSegments.push({
        type: 'line',
        x1: this.lastX,
        y1: this.lastY,
        x2: x,
        y2: y,
        color: this.brushColor,
        size: this.brushSize,
      });
    }

    this.ctx.stroke();

    this.lastX = x;
    this.lastY = y;
  }

  private handleCanvasClick(e: MouseEvent) {
    if (this.currentTool === 'text' && this.isTextPlacementMode) {
      this.placeText(e);
    }
  }

  private onTouchStart(e: TouchEvent) {
    e.preventDefault();
    const touch = e.touches[0];

    if (this.currentTool === 'text' && this.isTextPlacementMode) {
      const mouseEvent = new MouseEvent('click', {
        clientX: touch.clientX,
        clientY: touch.clientY,
      });
      this.canvas.dispatchEvent(mouseEvent);
      return;
    }

    const mouseEvent = new MouseEvent('mousedown', {
      clientX: touch.clientX,
      clientY: touch.clientY,
    });
    this.canvas.dispatchEvent(mouseEvent);
  }

  private onTouchMove(e: TouchEvent) {
    e.preventDefault();
    const touch = e.touches[0];
    const mouseEvent = new MouseEvent('mousemove', {
      clientX: touch.clientX,
      clientY: touch.clientY,
    });
    this.canvas.dispatchEvent(mouseEvent);
  }

  private onTouchEnd(e: TouchEvent) {
    e.preventDefault();
    this.endPaint();
  }

  private dragText(e: MouseEvent) {
    if (!this.selectedTextElement) return;
    const rect = this.canvas.getBoundingClientRect();
    const scaleX = this.canvas.width / rect.width;
    const scaleY = this.canvas.height / rect.height;
    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;

    this.selectedTextElement.x = x + this.dragOffsetX;
    this.selectedTextElement.y = y + this.dragOffsetY;

    // 用拖动前的画面做底重绘选中文字
    if (this.draggingCanvasContext) {
      this.ctx.putImageData(this.draggingCanvasContext, 0, 0);
    } else {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }
    this.ctx.font = this.selectedTextElement.font;
    this.ctx.fillStyle = this.selectedTextElement.color;
    this.ctx.fillText(this.selectedTextElement.text, this.selectedTextElement.x, this.selectedTextElement.y);
  }

  private findTextElementAt(e: MouseEvent): TextElement | null {
    const rect = this.canvas.getBoundingClientRect();
    const scaleX = this.canvas.width / rect.width;
    const scaleY = this.canvas.height / rect.height;
    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;

    // 从最上层的文字开始命中检测
    for (let i = this.textElements.length - 1; i >= 0; i--) {
      const text = this.textElements[i];

      this.ctx.font = text.font;
      const textWidth = this.ctx.measureText(text.text).width;

      const fontSizeMatch = text.font.match(/(\d+)px/);
      const fontSize = fontSizeMatch ? parseInt(fontSizeMatch[1]) : 14;
      const textHeight = fontSize * 1.2; // 近似高度

      const margin = 5;
      if (x >= text.x - margin &&
        x <= text.x + textWidth + margin &&
        y >= text.y - textHeight + margin &&
        y <= text.y + margin) {
        return text;
      }
    }

    return null;
  }

  startTextPlacement() {
    const { text } = this.host.getTextConfig();
    if (!text.trim()) {
      void appAlert('请输入文字内容');
      return;
    }

    this.isTextPlacementMode = true;
    this.host.setCanvasTitle('点击画布放置文字');
    this.canvas.classList.add('text-placement-mode');
  }

  cancelTextPlacement() {
    this.isTextPlacementMode = false;
    this.canvas.classList.remove('text-placement-mode');

    this.isDraggingText = false;
    this.dragOffsetX = 0;
    this.dragOffsetY = 0;
    this.selectedTextElement = null;
    this.draggingCanvasContext = null;
  }

  private placeText(e: MouseEvent) {
    const rect = this.canvas.getBoundingClientRect();
    const scaleX = this.canvas.width / rect.width;
    const scaleY = this.canvas.height / rect.height;
    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;

    const { text, fontFamily, fontSize } = this.host.getTextConfig();

    let fontStyle = '';
    if (this.textItalic) fontStyle += 'italic ';
    if (this.textBold) fontStyle += 'bold ';

    const newText: TextElement = {
      text,
      x,
      y,
      font: `${fontStyle}${fontSize}px ${fontFamily}`,
      color: this.brushColor,
    };

    this.textElements.push(newText);

    // 选中新文字以便立刻拖动
    this.selectedTextElement = newText;
    this.draggingCanvasContext = this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height);

    this.ctx.font = newText.font;
    this.ctx.fillStyle = newText.color;
    this.ctx.fillText(newText.text, newText.x, newText.y);

    // 放置文字后的画面可由 textElements 完整重建，存增量步，不做整张 getImageData
    this.saveToHistory(undefined, true);

    this.host.onTextPlaced();
    this.isTextPlacementMode = false;
    this.canvas.classList.remove('text-placement-mode');
    this.host.setCanvasTitle('拖动新添加文字可调整位置');
  }

  // 抖动处理后重绘文字（避免文字被抖动破坏）
  redrawTextElements() {
    this.textElements.forEach(item => {
      this.ctx.font = item.font;
      this.ctx.fillStyle = item.color;
      this.ctx.fillText(item.text, item.x, item.y);
    });
  }

  // 抖动处理后重绘笔迹
  redrawLineSegments() {
    this.lineSegments.forEach(segment => {
      this.ctx.lineJoin = 'round';
      this.ctx.lineCap = 'round';
      this.ctx.strokeStyle = segment.color;
      this.ctx.lineWidth = segment.size;
      this.ctx.beginPath();

      if (segment.type === 'dot') {
        this.ctx.moveTo(segment.x, segment.y);
        this.ctx.lineTo(segment.x + 0.1, segment.y + 0.1);
      } else {
        this.ctx.moveTo(segment.x1, segment.y1);
        this.ctx.lineTo(segment.x2, segment.y2);
      }

      this.ctx.stroke();
    });
  }

  clearElements() {
    this.textElements = [];
    this.lineSegments = [];
  }
}
