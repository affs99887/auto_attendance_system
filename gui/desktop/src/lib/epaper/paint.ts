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
  imageData: ImageData;
  textElements: TextElement[];
  lineSegments: LineSegment[];
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
  // 历史快照总字节上限（约 64MB），大画布下据此动态下调实际步数，避免内存膨胀
  private readonly MAX_HISTORY_BYTES = 64 * 1024 * 1024;

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

  saveToHistory() {
    // 撤销后再绘制时丢弃后续历史
    this.historyStack = this.historyStack.slice(0, this.historyStep + 1);

    const canvasState: CanvasState = {
      imageData: this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height),
      textElements: JSON.parse(JSON.stringify(this.textElements)),
      lineSegments: JSON.parse(JSON.stringify(this.lineSegments)),
    };

    this.historyStack.push(canvasState);
    this.historyStep++;

    // 单张快照字节数 = w*h*4，据总字节预算动态算出本尺寸下允许的步数
    const bytesPerSnapshot = this.canvas.width * this.canvas.height * 4;
    const dynamicMax = bytesPerSnapshot > 0
      ? Math.max(1, Math.min(this.MAX_HISTORY, Math.floor(this.MAX_HISTORY_BYTES / bytesPerSnapshot)))
      : this.MAX_HISTORY;

    // 超出动态上限则淘汰最旧快照（可能一次淘汰多张）
    while (this.historyStack.length > dynamicMax) {
      this.historyStack.shift();
      this.historyStep--;
    }

    this.notifyHistoryChange();
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
      this.ctx.putImageData(state.imageData, 0, 0);
      this.textElements = JSON.parse(JSON.stringify(state.textElements));
      this.lineSegments = JSON.parse(JSON.stringify(state.lineSegments));
      this.notifyHistoryChange();
    }
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

    // 以空白画布初始化历史
    this.saveToHistory();
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
    if (this.painting || this.isDraggingText) {
      this.saveToHistory();
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

    this.saveToHistory();

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
