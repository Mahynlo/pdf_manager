// Iconos de la app: los de Lucide (https://lucide.dev, paquete `lucide`) y unos pocos propios que
// Lucide no tiene (assets/icons-custom.json). Se usan por nombre: <Icon name="save"> en los
// componentes, `icon: 'save'` en menús y datos, e `ic('save')` en el código imperativo del lienzo.
//
// Un icono nuevo: búscalo en lucide.dev, impórtalo aquí y añádelo a ICONS con el nombre que usará la
// app (el de Lucide, en minúsculas y con guiones). Solo llega a la app lo que se importa aquí.
//
//   button.append(ic('save'));
import {
  ALargeSmall, ArrowDown, ArrowDownAZ, ArrowRight, ArrowUp, ArrowUpDown, ArrowUpRight, BookOpen, Brush, Calendar,
  ChartBar, Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, ChevronsLeft, ChevronsRight, Circle,
  CircleCheck, CircleExclamationPoint, CircleQuestionMark, CircleStop, Clock, Compass, Copy, CreditCard,
  Crop, Download, EllipsisVertical, Eraser, Eye, EyeOff, File, FilePlus, FileStack, FileText, Files,
  Fingerprint, Folder, FolderOpen, FolderPlus, Globe, Hand, Hash, Highlighter, House, IdCard, Image, Images,
  Info, Keyboard, Landmark, Lightbulb, LineSquiggle, List, ListTree, Lock, LockOpen, Mail, MessageCircle,
  MessageSquare, Minus, Moon, PaintBucket, Palette, Pipette, PanelLeft, PanelRight, PenLine, Pencil, Pentagon, Phone,
  Play, Plus, Pointer, Printer, Redo, Rocket, RotateCcw, RotateCw, Rows2, Save, ScanSearch, ScanText,
  Scissors, Search, Send, Settings, Shield, ShieldCheck, Signature, Sparkles, Square, SquareDashed, Stamp, Star,
  Strikethrough, Sun, Table, Tag, Terminal, TextCursor, Timer, Trash, TriangleAlert, Type, Underline, Undo, Upload,
  X, Zap,
  type IconNode,
} from 'lucide';
import custom from '../assets/icons-custom.json';

/** Nombre en la app → icono de Lucide (algunos nombres son los de versiones anteriores de Lucide). */
const ICONS: Record<string, IconNode> = {
  'a-large-small': ALargeSmall,
  'arrow-down': ArrowDown,
  'arrow-down-a-z': ArrowDownAZ,
  'arrow-right': ArrowRight,
  'arrow-up': ArrowUp,
  'arrow-up-down': ArrowUpDown,
  'arrow-up-right': ArrowUpRight,
  'bar-chart': ChartBar,
  'book-open': BookOpen,
  'brush': Brush,
  'calendar': Calendar,
  'check': Check,
  'chevron-down': ChevronDown,
  'chevron-left': ChevronLeft,
  'chevron-right': ChevronRight,
  'chevron-up': ChevronUp,
  'chevrons-left': ChevronsLeft,
  'chevrons-right': ChevronsRight,
  'circle': Circle,
  'circle-alert': CircleExclamationPoint,
  'circle-check': CircleCheck,
  'circle-help': CircleQuestionMark,
  'circle-stop': CircleStop,
  'clock': Clock,
  'compass': Compass,
  'copy': Copy,
  'credit-card': CreditCard,
  'crop': Crop,
  'download': Download,
  'eraser': Eraser,
  'eye': Eye,
  'eye-off': EyeOff,
  'file': File,
  'file-plus': FilePlus,
  'file-stack': FileStack,
  'file-text': FileText,
  'files': Files,
  'fingerprint': Fingerprint,
  'folder': Folder,
  'folder-open': FolderOpen,
  'folder-plus': FolderPlus,
  'globe': Globe,
  'hand': Hand,
  'hash': Hash,
  'highlighter': Highlighter,
  'home': House,
  'id-card': IdCard,
  'image': Image,
  'images': Images,
  'info': Info,
  'keyboard': Keyboard,
  'landmark': Landmark,
  'lightbulb': Lightbulb,
  'list': List,
  'list-tree': ListTree,
  'lock': Lock,
  'lock-open': LockOpen,
  'mail': Mail,
  'message-circle': MessageCircle,
  'message-square': MessageSquare,
  'minus': Minus,
  'moon': Moon,
  'more-vertical': EllipsisVertical,
  'paint-bucket': PaintBucket,
  'pipette': Pipette,
  'palette': Palette,
  'panel-left': PanelLeft,
  'panel-right': PanelRight,
  'pen-line': PenLine,
  'pencil': Pencil,
  'pentagon': Pentagon,
  'phone': Phone,
  'play': Play,
  'plus': Plus,
  'pointer': Pointer,
  'printer': Printer,
  'redo': Redo,
  'rocket': Rocket,
  'rotate-ccw': RotateCcw,
  'rotate-cw': RotateCw,
  'rows': Rows2,
  'save': Save,
  'scan-search': ScanSearch,
  'scan-text': ScanText,
  'scissors': Scissors,
  'search': Search,
  'send': Send,
  'settings': Settings,
  'shield': Shield,
  'shield-check': ShieldCheck,
  'signature': Signature,
  'sparkles': Sparkles,
  'square': Square,
  'square-dashed': SquareDashed,
  'squiggle': LineSquiggle,
  'stamp': Stamp,
  'star': Star,
  'strikethrough': Strikethrough,
  'sun': Sun,
  'table': Table,
  'tag': Tag,
  'terminal': Terminal,
  'text-cursor': TextCursor,
  'timer': Timer,
  'trash': Trash,
  'triangle-alert': TriangleAlert,
  'type': Type,
  'underline': Underline,
  'upload': Upload,
  'undo': Undo,
  'x': X,
  'zap': Zap,
};

const escape = (value: string | number) => String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

/** Los elementos de un icono de Lucide como SVG (`<path d="…"/>`…). */
function toSvg(node: IconNode): string {
  return node
    .map(([tag, attrs]) => `<${tag} ${Object.entries(attrs).map(([k, v]) => `${k}="${escape(v as string | number)}"`).join(' ')}/>`)
    .join('');
}

/** Trazos SVG de cada icono, por nombre. */
export const paths: Record<string, string> = {
  ...Object.fromEntries(Object.entries(ICONS).map(([name, node]) => [name, toSvg(node)])),
  ...(custom as Record<string, string>),
};

export function ic(name: string, size = 16): SVGSVGElement {
  if (!(name in paths)) console.warn(`Icono desconocido: ${name}`);
  const tpl = document.createElement('template');
  tpl.innerHTML =
    `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] ?? ''}</svg>`;
  return tpl.content.firstChild as SVGSVGElement;
}
