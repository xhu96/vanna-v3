export { VannaChat } from './components/vanna-chat';
export { VannaMessage } from './components/vanna-message';
export { VannaStatusBar } from './components/vanna-status-bar';
export { VannaProgressTracker } from './components/vanna-progress-tracker';
export { PlotlyChart } from './components/plotly-chart';
export { VegaLiteChart } from './components/vega-lite-chart';
export {
  VannaApiClient,
  VannaHttpError,
  apiClient,
  resolveHttpUrl,
  resolveWebSocketUrl,
} from './services/api-client';
export {
  V3EventSequenceValidator,
  V3ProtocolError,
  V3RemoteError,
  normalizeV3Event,
  parseV3Event,
  parseV3PollResponse,
  validateChartSpec,
} from './types/events-v3';
export type {
  ApiClientConfig,
  ApiProtocol,
  ChatRequest,
  ChatResponse,
  ChatStreamChunk,
  RequestOptions,
} from './services/api-client';
export type {
  ChartSpec,
  V3ChatEvent,
  V3EventEnvelope,
  V3EventType,
  V3PayloadByType,
  V3PollResponse,
} from './types/events-v3';

// Rich component system
export {
  ComponentRegistry,
  ComponentManager,
  CardComponentRenderer,
  TaskListComponentRenderer,
  ProgressBarComponentRenderer,
  NotificationComponentRenderer,
  StatusIndicatorComponentRenderer,
  TextComponentRenderer
} from './components/rich-component-system';

// Rich component styles are injected automatically by the ComponentManager
