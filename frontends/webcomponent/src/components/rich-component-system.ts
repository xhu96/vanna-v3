/**
 * Rich Component System for Vanna Agents
 *
 * Provides a generic component registry and rendering system that can display
 * any rich component sent from the Python backend.
 */

import { richComponentStyleText } from '../styles/rich-component-styles.js';
import {
  buildStaticArtifactDocument,
  escapeHtmlText,
  renderSanitizedMarkdown,
  sanitizeArtifactContent,
  sanitizePlainText,
  setSanitizedHtml,
} from '../security/content-security.js';

// Component interfaces matching Python backend
export interface RichComponent {
  id: string;
  type: string;
  lifecycle: 'create' | 'update' | 'replace' | 'remove';
  data: Record<string, any>;
  children: string[];
  timestamp: string;
  visible: boolean;
  interactive: boolean;
}

// Artifact event interfaces
export interface ArtifactOpenedEventDetail {
  // Core identification
  artifactId: string;

  // Artifact content
  content: string; // Sanitized static markup; JavaScript is represented as source markup.
  type: string;
  title?: string;
  description?: string;

  // Trigger context
  trigger: 'created' | 'user-action'; // How this event was fired

  // Control
  preventDefault: () => void; // Prevent default behavior

  // Helpers
  getStandaloneHTML: () => string; // Full page HTML with dependencies

  // Metadata
  timestamp: string;
}

declare global {
  interface GlobalEventHandlersEventMap {
    'artifact-opened': CustomEvent<ArtifactOpenedEventDetail>;
  }
}


const RICH_COMPONENT_STYLE_ATTR = 'data-vanna-rich-component-styles';

const UI_ICONS = Object.freeze({
  check: '<svg class="vanna-inline-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8.2l3 3L13 4.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  close: '<svg class="vanna-inline-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M4 4l8 8m0-8l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  info: '<svg class="vanna-inline-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true"><circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.4"/><path d="M8 7.2v3.4M8 5.1h.01" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  warning: '<svg class="vanna-inline-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M8 2.5l6 10.5H2L8 2.5z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M8 6v3.2M8 11.2h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  pending: '<svg class="vanna-inline-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true"><circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.4"/><path d="M8 4.8v3.5l2.2 1.4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  running: '<svg class="vanna-inline-icon icon-spinning" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M13 8a5 5 0 11-1.46-3.54" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M11.5 2.8v2.7H8.8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  chevron: '<svg class="vanna-inline-icon chevron-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M4.5 6l3.5 3.5L11.5 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  edit: '<svg class="vanna-inline-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 11.8V13h1.2l7.9-7.9-1.2-1.2L3 11.8zM10 4.8l1.2 1.2" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
  maximize: '<svg class="vanna-inline-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true"><rect x="3" y="3" width="10" height="10" rx="1" stroke="currentColor" stroke-width="1.4"/></svg>',
  external: '<svg class="vanna-inline-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M9 3h4v4M13 3L7.5 8.5M11.5 9v3.5h-8v-8H7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
});

function ensureRichComponentStyles(container: HTMLElement): void {
  const doc = container.ownerDocument;
  if (!doc) {
    return;
  }

  if (container.querySelector(`style[${RICH_COMPONENT_STYLE_ATTR}]`)) {
    return;
  }

  const styleEl = doc.createElement('style');
  styleEl.setAttribute(RICH_COMPONENT_STYLE_ATTR, 'true');
  styleEl.textContent = richComponentStyleText;
  container.prepend(styleEl);
}

export interface ComponentUpdate {
  operation: 'create' | 'update' | 'replace' | 'remove' | 'reorder' | 'bulk_update';
  target_id: string;
  component?: RichComponent;
  updates?: Record<string, any>;
  position?: any;
  timestamp: string;
  batch_id?: string;
}

// Component renderer interface
export interface ComponentRenderer {
  render(component: RichComponent): HTMLElement;
  update(element: HTMLElement, component: RichComponent, updates?: Record<string, any>): void;
  remove(element: HTMLElement): void;
}

// Base component renderer with common functionality
export abstract class BaseComponentRenderer implements ComponentRenderer {
  abstract render(component: RichComponent): HTMLElement;

  update(element: HTMLElement, component: RichComponent, _updates?: Record<string, any>): void {
    // Default implementation - re-render completely
    const newElement = this.render(component);
    element.parentNode?.replaceChild(newElement, element);
  }

  remove(element: HTMLElement): void {
    element.remove();
  }

}

// Card component renderer
export class CardComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const card = document.createElement('div');
    card.className = 'rich-component rich-card';
    card.dataset.componentId = component.id;

    const { title, content, subtitle, icon, status, actions = [], collapsible, collapsed } = component.data;

    setSanitizedHtml(card, `
      <div class="card-header ${collapsible ? 'collapsible' : ''}">
        ${icon ? `<span class="card-icon">${icon}</span>` : ''}
        <div class="card-title-section">
          <h3 class="card-title">${title}</h3>
          ${subtitle ? `<p class="card-subtitle">${subtitle}</p>` : ''}
        </div>
        ${status ? `<span class="card-status status-${status}">${status}</span>` : ''}
        ${collapsible ? `<button class="card-toggle" type="button" aria-label="Toggle details" aria-expanded="${!collapsed}">${UI_ICONS.chevron}</button>` : ''}
      </div>
      <div class="card-content ${collapsed ? 'collapsed' : ''}">
        ${content}
      </div>
      ${actions && actions.length > 0 ? `
        <div class="card-actions">
          ${actions.map((action: any) => `
            <button class="card-action ${action.variant || 'secondary'}" data-action="${action.action}">
              ${action.label}
            </button>
          `).join('')}
        </div>
      ` : ''}
    `);


    // Add collapsible functionality
    if (collapsible) {
      const toggle = card.querySelector('.card-toggle') as HTMLButtonElement;
      const content = card.querySelector('.card-content') as HTMLElement;

      toggle?.addEventListener('click', () => {
        content.classList.toggle('collapsed');
        toggle.setAttribute('aria-expanded', String(!content.classList.contains('collapsed')));
      });
    }

    // Add click handlers for action buttons
    if (actions && actions.length > 0) {
      const actionButtons = card.querySelectorAll('.card-action') as NodeListOf<HTMLButtonElement>;

      actionButtons.forEach((button, index) => {
        const action = actions[index];

        if (action && action.action) {
          button.addEventListener('click', async () => {
            // Apply visual feedback
            button.disabled = true;
            button.classList.add('button-transitioning', 'button-clicked');

            // Find vanna-chat component and send message
            const vannaChat = document.querySelector('vanna-chat') as any;

            if (vannaChat && typeof vannaChat.sendMessage === 'function') {
              try {
                const success = await vannaChat.sendMessage(action.action);

                if (success) {
                  // Keep button disabled after successful action
                } else {
                  // Re-enable button on failure
                  button.disabled = false;
                  button.classList.remove('button-transitioning', 'button-clicked');
                }
              } catch {
                // Re-enable button on error
                button.disabled = false;
                button.classList.remove('button-transitioning', 'button-clicked');
              }
            } else {
              button.disabled = false;
              button.classList.remove('button-transitioning', 'button-clicked');
            }
          });
        }
      });
    }

    return card;
  }

  update(element: HTMLElement, component: RichComponent, updates?: Record<string, any>): void {
    if (!updates) return super.update(element, component);

    // Optimized updates for common properties
    if (updates.title) {
      const titleEl = element.querySelector('.card-title');
      if (titleEl) titleEl.textContent = updates.title;
    }

    if (updates.content) {
      const contentEl = element.querySelector('.card-content');
      if (contentEl) setSanitizedHtml(contentEl, updates.content, 'rich-text');
    }

    if (updates.status) {
      const statusEl = element.querySelector('.card-status');
      if (statusEl) {
        statusEl.className = `card-status status-${updates.status}`;
        statusEl.textContent = updates.status;
      }
    }

    // For complex updates, fall back to full re-render
    if (updates.actions || updates.collapsible) {
      super.update(element, component);
    }
  }
}

// Task list component renderer
export class TaskListComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-task-list';
    container.dataset.componentId = component.id;

    const { title, tasks = [], show_progress, show_timestamps } = component.data;

    const completedTasks = tasks.filter((task: any) => task.status === 'completed').length;
    const progress = tasks.length > 0 ? (completedTasks / tasks.length) * 100 : 0;

    setSanitizedHtml(container, `
      <div class="task-list-header">
        <h3 class="task-list-title">${title}</h3>
        ${show_progress ? `
          <div class="task-list-progress">
            <span class="progress-text">${completedTasks}/${tasks.length} completed</span>
            <div class="progress-bar">
              <div class="progress-fill" style="width: ${progress}%"></div>
            </div>
          </div>
        ` : ''}
      </div>
      <div class="task-list-items">
        ${tasks.map((task: any) => this.renderTask(task, show_timestamps)).join('')}
      </div>
    `);


    return container;
  }

  private renderTask(task: any, showTimestamps: boolean): string {
    const statusIcon = this.getStatusIcon(task.status);
    const progressBar = task.progress !== null && task.progress !== undefined ? `
      <div class="task-progress">
        <div class="task-progress-bar">
          <div class="task-progress-fill" style="width: ${task.progress * 100}%"></div>
        </div>
        <span class="task-progress-text">${Math.round(task.progress * 100)}%</span>
      </div>
    ` : '';

    return `
      <div class="task-item status-${task.status}" data-task-id="${task.id}">
        <div class="task-icon">${statusIcon}</div>
        <div class="task-content">
          <div class="task-title">${task.title}</div>
          ${task.description ? `<div class="task-description">${task.description}</div>` : ''}
          ${progressBar}
          ${showTimestamps && task.created_at ? `
            <div class="task-timestamp">
              Created: ${new Date(task.created_at).toLocaleString()}
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }

  private getStatusIcon(status: string): string {
    switch (status) {
      case 'completed': return UI_ICONS.check;
      case 'running': return UI_ICONS.running;
      case 'failed': return UI_ICONS.close;
      default: return UI_ICONS.pending;
    }
  }
}

// Progress bar component renderer
export class ProgressBarComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-progress-bar';
    container.dataset.componentId = component.id;

    const { value, label, show_percentage, status, animated } = component.data;
    const percentage = Math.round(value * 100);

    setSanitizedHtml(container, `
      <div class="progress-header">
        ${label ? `<span class="progress-label">${label}</span>` : ''}
        ${show_percentage ? `<span class="progress-percentage">${percentage}%</span>` : ''}
      </div>
      <div class="progress-track">
        <div class="progress-fill ${animated ? 'animated' : ''} ${status ? `status-${status}` : ''}"
             style="width: ${percentage}%"></div>
      </div>
    `);


    return container;
  }

  update(element: HTMLElement, component: RichComponent, updates?: Record<string, any>): void {
    if (!updates) return super.update(element, component);

    if (updates.value !== undefined) {
      const fill = element.querySelector('.progress-fill') as HTMLElement;
      const percentage = Math.round(updates.value * 100);

      if (fill) {
        fill.style.width = `${percentage}%`;
      }

      const percentageEl = element.querySelector('.progress-percentage');
      if (percentageEl) {
        percentageEl.textContent = `${percentage}%`;
      }
    }

    if (updates.label) {
      const labelEl = element.querySelector('.progress-label');
      if (labelEl) labelEl.textContent = updates.label;
    }

    if (updates.status) {
      const fill = element.querySelector('.progress-fill') as HTMLElement;
      if (fill) {
        fill.className = fill.className.replace(/status-\w+/, `status-${updates.status}`);
      }
    }
  }
}

// Notification component renderer
export class NotificationComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-notification';
    container.dataset.componentId = component.id;

    const { message, title, level = 'info', icon, dismissible, auto_dismiss, actions = [] } = component.data;

    const levelIcon = icon || this.getLevelIcon(level);
    const dismissButton = dismissible ? `
      <button class="notification-dismiss" type="button" aria-label="Dismiss">${UI_ICONS.close}</button>
    ` : '';

    setSanitizedHtml(container, `
      <div class="notification-content level-${level}">
        ${levelIcon ? `<span class="notification-icon">${levelIcon}</span>` : ''}
        <div class="notification-body">
          ${title ? `<div class="notification-title">${title}</div>` : ''}
          <div class="notification-message">${message}</div>
        </div>
        ${actions.length > 0 ? `
          <div class="notification-actions">
            ${actions.map((action: any) => `
              <button class="notification-action ${action.variant || 'secondary'}" data-action="${action.action}">
                ${action.label}
              </button>
            `).join('')}
          </div>
        ` : ''}
        ${dismissButton}
      </div>
    `);

    container.querySelector('.notification-dismiss')?.addEventListener('click', () => {
      container.remove();
    });

    // Auto-dismiss functionality
    if (auto_dismiss && component.data.auto_dismiss_delay) {
      setTimeout(() => {
        if (container.parentElement) {
          container.remove();
        }
      }, component.data.auto_dismiss_delay);
    }


    return container;
  }

  private getLevelIcon(level: string): string {
    switch (level) {
      case 'success': return UI_ICONS.check;
      case 'warning': return UI_ICONS.warning;
      case 'error': return UI_ICONS.close;
      case 'info':
      default: return UI_ICONS.info;
    }
  }
}

// Status indicator component renderer
export class StatusIndicatorComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-status-indicator';
    container.dataset.componentId = component.id;

    const { status, message, icon, pulse } = component.data;

    const statusIcon = icon || this.getStatusIcon(status);
    const pulseClass = pulse ? 'pulse' : '';

    setSanitizedHtml(container, `
      <div class="status-indicator-content status-${status} ${pulseClass}">
        <span class="status-icon">${statusIcon}</span>
        <span class="status-message">${message}</span>
      </div>
    `);


    return container;
  }

  private getStatusIcon(status: string): string {
    switch (status) {
      case 'loading': return UI_ICONS.running;
      case 'success': return UI_ICONS.check;
      case 'warning': return UI_ICONS.warning;
      case 'error': return UI_ICONS.close;
      default: return UI_ICONS.info;
    }
  }

  update(element: HTMLElement, component: RichComponent, updates?: Record<string, any>): void {
    if (!updates) return super.update(element, component);

    const content = element.querySelector('.status-indicator-content');
    if (content && updates.status) {
      content.className = content.className.replace(/status-\w+/, `status-${updates.status}`);
    }

    if (updates.pulse !== undefined) {
      const content = element.querySelector('.status-indicator-content');
      if (content) {
        if (updates.pulse) {
          content.classList.add('pulse');
        } else {
          content.classList.remove('pulse');
        }
      }
    }

    if (updates.message) {
      const messageEl = element.querySelector('.status-message');
      if (messageEl) {
        messageEl.textContent = updates.message;
      }
    }
  }
}

// DataFrame component renderer
export class DataFrameComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-dataframe';
    container.dataset.componentId = component.id;

    const {
      data = [],
      columns = [],
      title,
      description,
      row_count = 0,
      column_count = 0,
      max_rows_displayed = 100,
      searchable = true,
      sortable = true,
      filterable = true,
      exportable = true,
      striped = true,
      bordered = true,
      compact = false,
      column_types = {}
    } = component.data;

    // Limit displayed rows
    const displayedData = data.slice(0, max_rows_displayed);
    const hasMoreRows = data.length > max_rows_displayed;

    let headerHTML = '';
    if (title || description) {
      headerHTML = `
        <div class="dataframe-header">
          ${title ? `<h3 class="dataframe-title">${title}</h3>` : ''}
          ${description ? `<p class="dataframe-description">${description}</p>` : ''}
          <div class="dataframe-meta">
            <span class="row-count">${row_count} rows</span>
            <span class="column-count">${column_count} columns</span>
          </div>
        </div>
      `;
    }

    let actionsHTML = '';
    if (searchable || exportable || filterable) {
      actionsHTML = `
        <div class="dataframe-actions">
          ${searchable ? `
            <div class="dataframe-search">
              <input type="text" placeholder="Search..." class="search-input">
            </div>
          ` : ''}
          ${exportable ? `
            <button class="export-btn" type="button" title="Export to CSV">Export CSV</button>
          ` : ''}
        </div>
      `;
    }

    let tableHTML = '';
    if (columns.length > 0 && displayedData.length > 0) {
      const tableClasses = [
        'dataframe-table',
        striped ? 'striped' : '',
        bordered ? 'bordered' : '',
        compact ? 'compact' : ''
      ].filter(Boolean).join(' ');

      tableHTML = `
        <div class="dataframe-table-container">
          <table class="${tableClasses}">
            <thead>
              <tr>
                ${columns.map((col: string) => `
                  <th class="${sortable ? 'sortable' : ''}" data-column="${col}">
                    ${col}
                    ${sortable ? '<span class="sort-indicator"></span>' : ''}
                  </th>
                `).join('')}
              </tr>
            </thead>
            <tbody>
              ${displayedData.map((row: any) => `
                <tr>
                  ${columns.map((col: string) => {
                    const value = row[col];
                    const columnType = column_types[col] || 'string';
                    const formattedValue = this.formatCellValue(value, columnType);
                    return `<td class="cell-${columnType}">${formattedValue}</td>`;
                  }).join('')}
                </tr>
              `).join('')}
            </tbody>
          </table>
          ${hasMoreRows ? `
            <div class="dataframe-truncated">
              <em>Showing ${max_rows_displayed} of ${row_count} rows</em>
            </div>
          ` : ''}
        </div>
      `;
    } else {
      tableHTML = `
        <div class="dataframe-empty">
          <p>No data to display</p>
        </div>
      `;
    }

    setSanitizedHtml(container, `
      ${headerHTML}
      ${actionsHTML}
      ${tableHTML}
    `);


    // Add event listeners
    this.attachEventListeners(container, displayedData, columns);

    return container;
  }

  private formatCellValue(value: any, columnType: string): string {
    if (value === null || value === undefined) {
      return '<em class="null-value">NULL</em>';
    }

    switch (columnType) {
      case 'number':
        return typeof value === 'number' ? value.toLocaleString() : String(value);
      case 'date':
        try {
          return new Date(value).toLocaleDateString();
        } catch {
          return String(value);
        }
      case 'boolean':
        return value ? 'Yes' : 'No';
      default:
        return escapeHtmlText(value);
    }
  }

  private attachEventListeners(container: HTMLElement, data: any[], columns: string[]): void {
    // Search functionality
    const searchInput = container.querySelector('.search-input') as HTMLInputElement;
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        const searchTerm = (e.target as HTMLInputElement).value.toLowerCase();
        this.filterTable(container, data, columns, searchTerm);
      });
    }

    // Export functionality
    const exportBtn = container.querySelector('.export-btn') as HTMLButtonElement;
    if (exportBtn) {
      exportBtn.addEventListener('click', () => {
        this.exportToCSV(data, columns);
      });
    }

    // Sort functionality
    const sortableHeaders = container.querySelectorAll('th.sortable');
    sortableHeaders.forEach(header => {
      header.addEventListener('click', (e) => {
        const column = (e.currentTarget as HTMLElement).dataset.column;
        if (column) {
          this.sortTable(container, data, columns, column);
        }
      });
    });
  }

  private filterTable(container: HTMLElement, data: any[], columns: string[], searchTerm: string): void {
    const tbody = container.querySelector('tbody');
    if (!tbody) return;

    const filteredData = data.filter(row => {
      return columns.some(col => {
        const value = String(row[col] || '').toLowerCase();
        return value.includes(searchTerm);
      });
    });

    setSanitizedHtml(tbody, filteredData.map(row => `
      <tr>
        ${columns.map(col => {
          const value = row[col];
          const formattedValue = this.formatCellValue(value, 'string');
          return `<td>${formattedValue}</td>`;
        }).join('')}
      </tr>
    `).join(''));
  }

  private sortTable(container: HTMLElement, data: any[], columns: string[], column: string): void {
    const tbody = container.querySelector('tbody');
    const header = Array.from(container.querySelectorAll<HTMLElement>('th[data-column]'))
      .find((candidate) => candidate.dataset.column === column);
    if (!tbody || !header) return;

    // Determine sort direction
    const currentSort = header.dataset.sortDirection || 'none';
    const newSort = currentSort === 'asc' ? 'desc' : 'asc';

    // Clear all sort indicators
    container.querySelectorAll('th[data-sort-direction]').forEach(h => {
      (h as HTMLElement).removeAttribute('data-sort-direction');
      const indicator = h.querySelector('.sort-indicator');
      if (indicator) indicator.textContent = '';
    });

    // Set new sort direction
    header.dataset.sortDirection = newSort;
    const indicator = header.querySelector('.sort-indicator');
    if (indicator) {
      indicator.textContent = newSort === 'asc' ? '↑' : '↓';
    }

    // Sort data
    const sortedData = [...data].sort((a, b) => {
      const aVal = a[column];
      const bVal = b[column];

      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return newSort === 'asc' ? aVal - bVal : bVal - aVal;
      }

      const aStr = String(aVal).toLowerCase();
      const bStr = String(bVal).toLowerCase();
      const comparison = aStr.localeCompare(bStr);
      return newSort === 'asc' ? comparison : -comparison;
    });

    // Update table
    setSanitizedHtml(tbody, sortedData.map(row => `
      <tr>
        ${columns.map(col => {
          const value = row[col];
          const formattedValue = this.formatCellValue(value, 'string');
          return `<td>${formattedValue}</td>`;
        }).join('')}
      </tr>
    `).join(''));
  }

  private exportToCSV(data: any[], columns: string[]): void {
    const csvContent = [
      columns.join(','),
      ...data.map(row =>
        columns.map(col => {
          const value = row[col];
          const strValue = value === null || value === undefined ? '' : String(value);
          // Escape quotes and wrap in quotes if contains comma, quote, or newline
          if (strValue.includes(',') || strValue.includes('"') || strValue.includes('\n')) {
            return `"${strValue.replace(/"/g, '""')}"`;
          }
          return strValue;
        }).join(',')
      )
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', 'data.csv');
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }
}

// Text component renderer
export class TextComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-text';
    container.dataset.componentId = component.id;

    const {
      content,
      markdown = false,
      code_language,
      font_size,
      font_weight,
      text_align
    } = component.data;

    // Apply text styling
    let textStyle = '';
    if (font_size) textStyle += `font-size: ${font_size}; `;
    if (font_weight) textStyle += `font-weight: ${font_weight}; `;
    if (text_align) textStyle += `text-align: ${text_align}; `;

    if (code_language) {
      // Code block
      setSanitizedHtml(container, `
        <pre class="text-code" style="${textStyle}"><code class="language-${code_language}">${escapeHtmlText(content)}</code></pre>
      `);
    } else if (markdown) {
      setSanitizedHtml(container, `
        <div class="text-markdown" style="${textStyle}">${renderSanitizedMarkdown(content)}</div>
      `);
    } else {
      // Plain text
      setSanitizedHtml(container, `
        <div class="text-content" style="${textStyle}">${escapeHtmlText(content)}</div>
      `);
    }


    return container;
  }

}

// Primitive Component Renderers (Domain-Agnostic)

// Status card component renderer
export class StatusCardComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-status-card';
    container.dataset.componentId = component.id;

    const { title, status, description, icon, actions = [], collapsible, collapsed, metadata = {} } = component.data;

    const statusIcon = icon || this.getStatusIcon(status);
    const hasMetadata = Object.keys(metadata).length > 0;

    setSanitizedHtml(container, `
      <div class="status-card-header ${collapsible ? 'collapsible' : ''}">
        <div class="status-card-icon">${statusIcon}</div>
        <div class="status-card-title-section">
          <h3 class="status-card-title">${title}</h3>
          <span class="status-card-badge status-${status}">${status}</span>
        </div>
        ${collapsible ? `<button class="status-card-toggle" type="button" aria-label="Toggle details" aria-expanded="${!collapsed}">${UI_ICONS.chevron}</button>` : ''}
      </div>
      ${description ? `
        <div class="status-card-content ${collapsed ? 'collapsed' : ''}">
          ${description}
        </div>
      ` : ''}
      ${hasMetadata ? `
        <details class="status-card-metadata">
          <summary class="status-card-metadata-summary">Parameters</summary>
          <div class="status-card-metadata-content">
            ${this.renderMetadataTable(metadata)}
          </div>
        </details>
      ` : ''}
      ${actions.length > 0 ? `
        <div class="status-card-actions">
          ${actions.map((action: any) => `
            <button class="status-card-action ${action.variant || 'secondary'}" data-action="${action.action}">
              ${action.label}
            </button>
          `).join('')}
        </div>
      ` : ''}
    `);

    // Add collapsible functionality
    if (collapsible) {
      const toggle = container.querySelector('.status-card-toggle') as HTMLButtonElement;
      const content = container.querySelector('.status-card-content') as HTMLElement;

      toggle?.addEventListener('click', () => {
        if (content) {
          content.classList.toggle('collapsed');
          toggle.setAttribute('aria-expanded', String(!content.classList.contains('collapsed')));
        }
      });
    }

    return container;
  }

  private renderMetadataTable(metadata: Record<string, any>): string {
    const rows = Object.entries(metadata).map(([key, value]) => {
      const formattedValue = this.formatMetadataValue(value);
      return `
        <tr>
          <td class="metadata-key">${escapeHtmlText(key)}</td>
          <td class="metadata-value">${formattedValue}</td>
        </tr>
      `;
    }).join('');

    return `
      <table class="metadata-table">
        <thead>
          <tr>
            <th>Parameter</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
      </table>
    `;
  }

  private formatMetadataValue(value: any): string {
    if (value === null) {
      return '<span class="metadata-null">null</span>';
    }
    if (value === undefined) {
      return '<span class="metadata-undefined">undefined</span>';
    }
    if (typeof value === 'boolean') {
      return `<span class="metadata-boolean">${value}</span>`;
    }
    if (typeof value === 'number') {
      return `<span class="metadata-number">${value}</span>`;
    }
    if (typeof value === 'string') {
      return `<span class="metadata-string">${escapeHtmlText(value)}</span>`;
    }
    if (Array.isArray(value) || typeof value === 'object') {
      return `<pre class="metadata-json">${JSON.stringify(value, null, 2)}</pre>`;
    }
    return escapeHtmlText(value);
  }

  private getStatusIcon(status: string): string {
    switch (status) {
      case 'pending': return UI_ICONS.pending;
      case 'running': return UI_ICONS.running;
      case 'completed': return UI_ICONS.check;
      case 'success': return UI_ICONS.check;
      case 'failed': return UI_ICONS.close;
      case 'error': return UI_ICONS.close;
      case 'warning': return UI_ICONS.warning;
      default: return UI_ICONS.info;
    }
  }
}

// Progress display component renderer
export class ProgressDisplayComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-progress-display';
    container.dataset.componentId = component.id;

    const { label, value, description, status, show_percentage, animated, indeterminate } = component.data;
    const percentage = Math.round(value * 100);

    setSanitizedHtml(container, `
      <div class="progress-display-container">
        <div class="progress-display-header">
          <span class="progress-display-label">${label}</span>
          ${show_percentage && !indeterminate ? `<span class="progress-display-percentage">${percentage}%</span>` : ''}
        </div>
        <div class="progress-display-track">
          <div class="progress-display-fill ${animated ? 'animated' : ''} ${status ? `status-${status}` : ''} ${indeterminate ? 'indeterminate' : ''}"
               style="width: ${indeterminate ? '100' : percentage}%"></div>
        </div>
        ${description ? `<div class="progress-display-description">${description}</div>` : ''}
      </div>
    `);

    return container;
  }
}

// Log viewer component renderer
export class LogViewerComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-log-viewer';
    container.dataset.componentId = component.id;

    const { title, entries = [], searchable, show_timestamps, auto_scroll } = component.data;

    setSanitizedHtml(container, `
      <div class="log-viewer-container">
        <div class="log-viewer-header">
          <h3 class="log-viewer-title">${title}</h3>
          ${searchable ? `
            <div class="log-viewer-search">
              <input type="text" placeholder="Search logs..." class="log-search-input">
            </div>
          ` : ''}
        </div>
        <div class="log-viewer-content ${auto_scroll ? 'auto-scroll' : ''}">
          ${entries.map((entry: any) => `
            <div class="log-entry log-${entry.level}">
              ${show_timestamps ? `<span class="log-timestamp">${new Date(entry.timestamp).toLocaleTimeString()}</span>` : ''}
              <span class="log-level">[${entry.level.toUpperCase()}]</span>
              <span class="log-message">${entry.message}</span>
            </div>
          `).join('')}
        </div>
      </div>
    `);

    // Auto-scroll to bottom if enabled
    if (auto_scroll) {
      const content = container.querySelector('.log-viewer-content');
      if (content) {
        content.scrollTop = content.scrollHeight;
      }
    }

    return container;
  }
}

// Badge component renderer
export class BadgeComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('span');
    container.className = `rich-component rich-badge badge-${component.data.variant} badge-${component.data.size}`;
    container.dataset.componentId = component.id;

    const { text, icon } = component.data;

    setSanitizedHtml(container, `
      ${icon ? `<span class="badge-icon">${icon}</span>` : ''}
      <span class="badge-text">${text}</span>
    `);

    return container;
  }
}

// Icon text component renderer
export class IconTextComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = `rich-component rich-icon-text icon-text-${component.data.variant} icon-text-${component.data.size} icon-text-${component.data.alignment}`;
    container.dataset.componentId = component.id;

    const { icon, text } = component.data;

    setSanitizedHtml(container, `
      <span class="icon-text-icon">${icon}</span>
      <span class="icon-text-text">${text}</span>
    `);

    return container;
  }
}

// Button component renderer
export class ButtonComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const button = document.createElement('button');
    button.className = `rich-component rich-button button-${component.data.variant} button-${component.data.size}`;
    button.dataset.componentId = component.id;

    const { label, action, disabled, icon, icon_position, full_width, loading } = component.data;

    if (disabled || loading) {
      button.disabled = true;
    }

    if (full_width) {
      button.classList.add('button-full-width');
    }

    if (loading) {
      button.classList.add('button-loading');
    }

    // Build button content
    let buttonContent = '';
    if (loading) {
      buttonContent = `<span class="button-spinner">${UI_ICONS.running}</span><span class="button-label">${label}</span>`;
    } else if (icon) {
      if (icon_position === 'right') {
        buttonContent = `<span class="button-label">${label}</span><span class="button-icon">${icon}</span>`;
      } else {
        buttonContent = `<span class="button-icon">${icon}</span><span class="button-label">${label}</span>`;
      }
    } else {
      buttonContent = `<span class="button-label">${label}</span>`;
    }

    setSanitizedHtml(button, buttonContent);

    // Add click handler
    if (action && !disabled && !loading) {
      button.addEventListener('click', async () => {
        // Apply visual feedback immediately
        button.disabled = true;
        button.classList.add('button-transitioning', 'button-clicked');

        // Find vanna-chat component and send message with button action
        const vannaChat = document.querySelector('vanna-chat') as any;

        if (vannaChat && typeof vannaChat.sendMessage === 'function') {
          try {
            const success = await vannaChat.sendMessage(action);
            if (!success) {
              // Restore button state if it wasn't originally disabled
              if (!disabled) {
                button.disabled = false;
              }
              button.classList.remove('button-transitioning', 'button-clicked');
            }
          } catch {
            // Restore button state if it wasn't originally disabled
            if (!disabled) {
              button.disabled = false;
            }
            button.classList.remove('button-transitioning', 'button-clicked');
          }
        } else {
          // Restore button state if it wasn't originally disabled
          if (!disabled) {
            button.disabled = false;
          }
          button.classList.remove('button-transitioning', 'button-clicked');
        }
      });
    }

    return button;
  }

  update(element: HTMLElement, component: RichComponent, updates?: Record<string, any>): void {
    if (!updates) return super.update(element, component);

    const button = element as HTMLButtonElement;

    if (updates.disabled !== undefined) {
      button.disabled = updates.disabled;
    }

    if (updates.loading !== undefined) {
      button.disabled = updates.loading;
      if (updates.loading) {
        button.classList.add('button-loading');
      } else {
        button.classList.remove('button-loading');
      }
    }

    if (updates.label || updates.icon || updates.icon_position) {
      // Re-render content
      super.update(element, component);
    }
  }
}

// Button group component renderer
export class ButtonGroupComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = `rich-component rich-button-group button-group-${component.data.orientation} button-group-spacing-${component.data.spacing} button-group-align-${component.data.align}`;
    container.dataset.componentId = component.id;

    const { buttons = [], full_width } = component.data;

    if (full_width) {
      container.classList.add('button-group-full-width');
    }

    // Render each button
    buttons.forEach((buttonConfig: any, index: number) => {
      const button = document.createElement('button');
      button.className = `rich-button button-${buttonConfig.variant || 'secondary'} button-${buttonConfig.size || 'medium'}`;
      button.dataset.buttonIndex = String(index);

      // Store original disabled state
      if (buttonConfig.disabled) {
        button.disabled = true;
        button.dataset.originallyDisabled = 'true';
      } else {
        button.dataset.originallyDisabled = 'false';
      }

      // Build button content
      let buttonContent = '';
      if (buttonConfig.icon) {
        if (buttonConfig.icon_position === 'right') {
          buttonContent = `<span class="button-label">${buttonConfig.label}</span><span class="button-icon">${buttonConfig.icon}</span>`;
        } else {
          buttonContent = `<span class="button-icon">${buttonConfig.icon}</span><span class="button-label">${buttonConfig.label}</span>`;
        }
      } else {
        buttonContent = `<span class="button-label">${buttonConfig.label}</span>`;
      }

      setSanitizedHtml(button, buttonContent);

      // Add click handler with enhanced functionality
      if (buttonConfig.action && !buttonConfig.disabled) {
        button.addEventListener('click', async () => {
          // Immediately apply visual changes to all buttons in the group
          this.applyButtonGroupClickState(container, index);

          // Find vanna-chat component and send message with button action
          const vannaChat = document.querySelector('vanna-chat') as any;

          if (vannaChat && typeof vannaChat.sendMessage === 'function') {
            try {
              const success = await vannaChat.sendMessage(buttonConfig.action);
              if (!success) {
                this.restoreButtonGroupState(container);
              }
            } catch {
              this.restoreButtonGroupState(container);
            }
          } else {
            this.restoreButtonGroupState(container);
          }
        });
      }

      container.appendChild(button);
    });

    return container;
  }

  private applyButtonGroupClickState(container: HTMLElement, clickedIndex: number): void {
    const buttons = container.querySelectorAll('button') as NodeListOf<HTMLButtonElement>;
    
    buttons.forEach((button, index) => {
      // Disable all buttons
      button.disabled = true;
      
      // Add transition class for animation
      button.classList.add('button-transitioning');
      
      if (index === clickedIndex) {
        // Highlight the clicked button
        button.classList.add('button-clicked', 'button-highlighted');
      } else {
        // Gray out other buttons
        button.classList.add('button-grayed-out');
      }
    });
  }

  private restoreButtonGroupState(container: HTMLElement): void {
    const buttons = container.querySelectorAll('button') as NodeListOf<HTMLButtonElement>;
    
    buttons.forEach((button) => {
      // Re-enable buttons (unless they were originally disabled)
      const originallyDisabled = button.dataset.originallyDisabled === 'true';
      if (!originallyDisabled) {
        button.disabled = false;
      }
      
      // Remove all state classes
      button.classList.remove(
        'button-clicked', 
        'button-highlighted', 
        'button-grayed-out',
        'button-transitioning'
      );
    });
  }
}

// Chart component renderer (declarative ChartSpec + legacy Plotly payloads)
export class ChartComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-chart';
    container.dataset.componentId = component.id;

    // ChartComponent serializes its custom payload under component.data.data.
    // We keep compatibility with older payloads where the Plotly dict was top-level.
    const chartPayload = component.data?.data ?? component.data ?? {};
    const title = component.data?.title || chartPayload?.title;

    if (title) {
      setSanitizedHtml(container, `
        <div class="chart-header">
          <h3 class="chart-title">${escapeHtmlText(title)}</h3>
        </div>
        <div class="chart-content"></div>
      `);
    }

    const mountTarget = (container.querySelector('.chart-content') as HTMLElement) || container;

    // New declarative format: Vega-Lite ChartSpec
    if (chartPayload.format === 'vega-lite' && chartPayload.spec) {
      const vegaElement = document.createElement('vega-lite-chart') as any;
      mountTarget.appendChild(vegaElement);
      requestAnimationFrame(() => {
        vegaElement.spec = chartPayload.spec;
        vegaElement.chartData = chartPayload.dataset || [];
      });
      return container;
    }

    // Declarative Plotly JSON path
    if (chartPayload.format === 'plotly-json' && chartPayload.spec?.data) {
      const chartElement = document.createElement('plotly-chart') as any;
      mountTarget.appendChild(chartElement);

      const vannaChat = document.querySelector('vanna-chat');
      if (vannaChat) {
        chartElement.theme = vannaChat.getAttribute('theme') || 'dark';
      }

      requestAnimationFrame(() => {
        chartElement.data = chartPayload.spec.data || [];
        chartElement.layout = chartPayload.spec.layout || {};
        chartElement.config = chartPayload.spec.config || {};
      });
      return container;
    }

    // Legacy Plotly payload path
    if (chartPayload.data && Array.isArray(chartPayload.data) && chartPayload.layout) {
      const chartElement = document.createElement('plotly-chart') as any;
      mountTarget.appendChild(chartElement);

      const vannaChat = document.querySelector('vanna-chat');
      if (vannaChat) {
        chartElement.theme = vannaChat.getAttribute('theme') || 'dark';
      }

      requestAnimationFrame(() => {
        chartElement.data = chartPayload.data;
        chartElement.layout = chartPayload.layout;
        chartElement.config = chartPayload.config || {};
      });
      return container;
    }

    // Fallback for invalid chart data
    setSanitizedHtml(container, `
      <div class="chart-error">
        <p>Invalid chart data format</p>
        <pre>${escapeHtmlText(JSON.stringify(component.data, null, 2).substring(0, 200))}...</pre>
      </div>
    `);

    return container;
  }
}

// Artifact component renderer
export class ArtifactComponentRenderer extends BaseComponentRenderer {
  private defaultPrevented = false;

  render(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-artifact';
    container.dataset.componentId = component.id;
    container.dataset.artifactId = component.data.artifact_id;

    const {
      artifact_type,
      title,
      description,
      editable,
      fullscreen_capable,
      external_renderable
    } = component.data;

    setSanitizedHtml(container, `
      <div class="artifact-header">
        <div class="artifact-meta">
          <h3 class="artifact-title">${escapeHtmlText(title || 'Artifact')}</h3>
          ${description ? `<p class="artifact-description">${description}</p>` : ''}
          <span class="artifact-type-badge">${escapeHtmlText(artifact_type)}</span>
        </div>
        <div class="artifact-controls">
          ${editable ? `<button class="artifact-btn edit-btn" type="button" aria-label="Edit" title="Edit">${UI_ICONS.edit}</button>` : ''}
          ${fullscreen_capable ? `<button class="artifact-btn fullscreen-btn" type="button" aria-label="Fullscreen" title="Fullscreen">${UI_ICONS.maximize}</button>` : ''}
          ${external_renderable ? `<button class="artifact-btn external-btn" type="button" aria-label="Open static view" title="Open static view">${UI_ICONS.external}</button>` : ''}
        </div>
      </div>
      <div class="artifact-preview"></div>
    `);

    container.querySelector('.artifact-preview')?.appendChild(
      this.createArtifactFrame(component, 'artifact-iframe')
    );

    // Attach event listeners
    this.attachEventListeners(container, component);

    // Fire artifact-opened event for creation
    const shouldRenderInChat = this.fireArtifactOpenedEvent(component, 'created', container);

    // If default was prevented, show a placeholder instead
    if (!shouldRenderInChat) {
      setSanitizedHtml(container, `
        <div class="artifact-placeholder">
          <div class="placeholder-content">
            <span class="placeholder-icon">${UI_ICONS.info}</span>
            <div class="placeholder-text">
              <strong>${escapeHtmlText(title || 'Artifact')}</strong> opened externally
              <div class="placeholder-type">${escapeHtmlText(artifact_type)}</div>
            </div>
            <button class="placeholder-reopen" type="button" aria-label="Reopen" title="Reopen">${UI_ICONS.external}</button>
          </div>
        </div>
      `);

      // Add reopen functionality
      const reopenBtn = container.querySelector('.placeholder-reopen') as HTMLButtonElement;
      if (reopenBtn) {
        reopenBtn.addEventListener('click', () => {
          this.fireArtifactOpenedEvent(component, 'user-action', container);
        });
      }
    }

    return container;
  }

  private createArtifactFrame(component: RichComponent, className: string): HTMLIFrameElement {
    const frame = document.createElement('iframe');
    frame.className = className;
    frame.setAttribute('sandbox', '');
    frame.setAttribute('allow', '');
    frame.setAttribute('referrerpolicy', 'no-referrer');
    frame.setAttribute('title', String(component.data.title || 'Artifact'));
    frame.srcdoc = this.generateStandaloneHTML(component);
    return frame;
  }

  private attachEventListeners(container: HTMLElement, component: RichComponent): void {
    // External button click
    const externalBtn = container.querySelector('.external-btn') as HTMLButtonElement;
    if (externalBtn) {
      externalBtn.addEventListener('click', () => {
        this.fireArtifactOpenedEvent(component, 'user-action', container);
      });
    }

    // Fullscreen button click
    const fullscreenBtn = container.querySelector('.fullscreen-btn') as HTMLButtonElement;
    if (fullscreenBtn) {
      fullscreenBtn.addEventListener('click', () => {
        this.openFullscreen(component);
      });
    }

    // Edit button click (placeholder for future implementation)
    const editBtn = container.querySelector('.edit-btn') as HTMLButtonElement;
    if (editBtn) {
      editBtn.addEventListener('click', () => {
        this.openEditor(component);
      });
    }
  }

  private fireArtifactOpenedEvent(component: RichComponent, trigger: 'created' | 'user-action', container: HTMLElement): boolean {
    this.defaultPrevented = false;

    const eventDetail: ArtifactOpenedEventDetail = {
      artifactId: sanitizePlainText(component.data.artifact_id),
      content: sanitizeArtifactContent(component.data.content, component.data.artifact_type),
      type: sanitizePlainText(component.data.artifact_type || 'html'),
      title: sanitizePlainText(component.data.title),
      description: sanitizePlainText(component.data.description),
      trigger,
      preventDefault: () => {
        this.defaultPrevented = true;
      },
      getStandaloneHTML: () => this.generateStandaloneHTML(component),
      timestamp: new Date().toISOString()
    };

    const event = new CustomEvent('artifact-opened', {
      detail: eventDetail,
      bubbles: true,
      cancelable: true
    });

    // Fire the event from the container element (should bubble up to vanna-chat)
    container.dispatchEvent(event);

    // Also dispatch directly on the vanna-chat element as backup
    const vannaChat = container.closest('vanna-chat');
    if (vannaChat) {
      vannaChat.dispatchEvent(new CustomEvent('artifact-opened', {
        detail: eventDetail,
        bubbles: true,
        cancelable: true
      }));
    }

    // Handle default behavior if not prevented and user triggered
    if (!this.defaultPrevented && trigger === 'user-action') {
      this.handleDefaultAction(component);
    }

    // Return whether we should render in chat (true if default not prevented)
    return !this.defaultPrevented;
  }

  private generateStandaloneHTML(component: RichComponent): string {
    return buildStaticArtifactDocument(
      component.data.content,
      component.data.artifact_type,
      component.data.title
    );
  }

  private handleDefaultAction(component: RichComponent): void {
    this.openFullscreen(component);
  }

  private openFullscreen(component: RichComponent): void {
    // Create fullscreen overlay
    const overlay = document.createElement('div');
    overlay.className = 'artifact-fullscreen-overlay';

    const header = document.createElement('div');
    header.className = 'fullscreen-header';
    const heading = document.createElement('h3');
    heading.textContent = String(component.data.title || 'Artifact');
    const closeBtn = document.createElement('button');
    closeBtn.className = 'close-fullscreen';
    closeBtn.textContent = '✕';
    header.append(heading, closeBtn);

    const content = document.createElement('div');
    content.className = 'fullscreen-content';
    const iframe = this.createArtifactFrame(component, 'fullscreen-iframe');
    content.appendChild(iframe);
    overlay.append(header, content);

    // Add styles
    overlay.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: white;
      z-index: 10000;
      display: flex;
      flex-direction: column;
    `;

    header.style.cssText = `
      padding: 16px;
      border-bottom: 1px solid #eee;
      display: flex;
      justify-content: space-between;
      align-items: center;
    `;

    content.style.cssText = `
      flex: 1;
      padding: 16px;
    `;

    iframe.style.cssText = `
      width: 100%;
      height: 100%;
      border: none;
    `;

    // Close button functionality
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        close();
      }
    };
    const close = () => {
      overlay.remove();
      document.removeEventListener('keydown', handleEscape);
    };
    closeBtn.addEventListener('click', close);
    document.addEventListener('keydown', handleEscape);

    document.body.appendChild(overlay);
  }

  private openEditor(_component: RichComponent): void {
    // Placeholder for future editor implementation
  }
}

// User message component renderer
export class UserMessageComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const messageEl = document.createElement('vanna-message');
    messageEl.setAttribute('theme', 'light'); // Could be made dynamic
    messageEl.dataset.componentId = component.id;
    
    // Set properties for vanna-message
    (messageEl as any).content = component.data.content || '';
    (messageEl as any).type = 'user';
    (messageEl as any).timestamp = Date.parse(component.timestamp);
    
    return messageEl;
  }
}

// Assistant message component renderer  
export class AssistantMessageComponentRenderer extends BaseComponentRenderer {
  render(component: RichComponent): HTMLElement {
    const messageEl = document.createElement('vanna-message');
    messageEl.setAttribute('theme', 'light'); // Could be made dynamic
    messageEl.dataset.componentId = component.id;
    
    // Set properties for vanna-message
    (messageEl as any).content = component.data.content || '';
    (messageEl as any).type = 'assistant';
    (messageEl as any).timestamp = Date.parse(component.timestamp);
    
    return messageEl;
  }
}

// Component registry for managing all component types
export class ComponentRegistry {
  private renderers: Map<string, ComponentRenderer> = new Map();
  private readonly webComponentProperties: Record<string, ReadonlySet<string>> = {
    'rich-card': new Set([
      'actions', 'collapsed', 'collapsible', 'content', 'icon', 'markdown', 'status',
      'subtitle', 'title',
    ]),
    'rich-progress-bar': new Set([
      'animated', 'description', 'indeterminate', 'label', 'showPercentage', 'status',
      'value',
    ]),
    'rich-task-list': new Set(['showProgress', 'showTimestamps', 'tasks', 'title']),
  };
  private readonly webComponentPropertyAliases: Record<string, string> = {
    show_percentage: 'showPercentage',
    show_progress: 'showProgress',
    show_timestamps: 'showTimestamps',
  };

  constructor() {
    // Register primitive component renderers (domain-agnostic)
    this.register('status_card', new StatusCardComponentRenderer());
    this.register('progress_display', new ProgressDisplayComponentRenderer());
    this.register('log_viewer', new LogViewerComponentRenderer());
    this.register('badge', new BadgeComponentRenderer());
    this.register('icon_text', new IconTextComponentRenderer());

    // Register existing component renderers
    this.register('card', new CardComponentRenderer());
    this.register('task_list', new TaskListComponentRenderer());
    this.register('progress_bar', new ProgressBarComponentRenderer());
    this.register('notification', new NotificationComponentRenderer());
    this.register('status_indicator', new StatusIndicatorComponentRenderer());
    this.register('text', new TextComponentRenderer());
    this.register('dataframe', new DataFrameComponentRenderer());
    this.register('chart', new ChartComponentRenderer());

    // Register interactive component renderers
    this.register('button', new ButtonComponentRenderer());
    this.register('button_group', new ButtonGroupComponentRenderer());

    // Register artifact component renderer
    this.register('artifact', new ArtifactComponentRenderer());

    // Register message component renderers
    this.register('user-message', new UserMessageComponentRenderer());
    this.register('assistant-message', new AssistantMessageComponentRenderer());
  }

  register(type: string, renderer: ComponentRenderer): void {
    this.renderers.set(type, renderer);
  }

  render(component: RichComponent): HTMLElement {
    // Check if this is a component that should use web components
    const webComponentTag = this.getWebComponentTag(component.type);
    if (webComponentTag) {
      return this.renderWebComponent(webComponentTag, component);
    }

    // Use the old renderer system for other components
    const renderer = this.renderers.get(component.type);
    if (!renderer) {
      return this.renderFallback(component);
    }
    return renderer.render(component);
  }

  private getWebComponentTag(type: string): string | null {
    const mapping: Record<string, string> = {
      'card': 'rich-card',
      'task_list': 'rich-task-list',
      'progress_bar': 'rich-progress-bar',
      // We'll add more mappings as we convert other components
    };
    return mapping[type] || null;
  }

  private renderWebComponent(tagName: string, component: RichComponent): HTMLElement {
    const element = document.createElement(tagName) as any;
    const allowedProperties = this.webComponentProperties[tagName] ?? new Set<string>();

    // Never allow payload keys such as innerHTML to become DOM properties.
    Object.entries(component.data).forEach(([key, value]) => {
      const property = this.webComponentPropertyAliases[key] ?? key;
      if (allowedProperties.has(property)) {
        element[property] = value;
      }
    });

    // Set theme to match the parent VannaChat theme
    element.setAttribute('theme', this.getCurrentTheme());


    return element;
  }

  private getCurrentTheme(): string {
    // Try to get theme from the parent VannaChat component
    const vannaChat = document.querySelector('vanna-chat');
    if (vannaChat) {
      return vannaChat.getAttribute('theme') || 'dark';
    }
    return 'dark';
  }


  update(element: HTMLElement, component: RichComponent, updates?: Record<string, any>): void {
    const renderer = this.renderers.get(component.type);
    if (renderer) {
      renderer.update(element, component, updates);
    }
  }

  remove(element: HTMLElement): void {
    element.remove();
  }

  private renderFallback(component: RichComponent): HTMLElement {
    const container = document.createElement('div');
    container.className = 'rich-component rich-fallback';
    container.dataset.componentId = component.id;

    setSanitizedHtml(container, `
      <div class="fallback-header">
        <strong>Unknown Component: ${escapeHtmlText(component.type)}</strong>
      </div>
      <pre class="fallback-data">${escapeHtmlText(JSON.stringify(component.data, null, 2))}</pre>
    `);

    return container;
  }
}

// Component manager for handling component lifecycle
export class ComponentManager {
  private components: Map<string, RichComponent> = new Map();
  private elements: Map<string, HTMLElement> = new Map();
  private registry: ComponentRegistry = new ComponentRegistry();
  private container: HTMLElement;
  private readonly sharedFields = new Set([
    'id',
    'type',
    'lifecycle',
    'layout',
    'theme',
    'children',
    'timestamp',
    'visible',
    'interactive',
  ]);

  constructor(container: HTMLElement) {
    this.container = container;
    ensureRichComponentStyles(this.container);
  }

  processUpdate(update: ComponentUpdate): void {
    // Handle UI state updates with special processing
    if (update.component && this.isUIStateUpdate(update.component)) {
      this.processUIStateUpdate(update.component);
      return;
    }

    switch (update.operation) {
      case 'create':
        this.createComponent(update);
        break;
      case 'update':
        this.updateComponent(update);
        break;
      case 'replace':
        this.replaceComponent(update);
        break;
      case 'remove':
        this.removeComponent(update);
        break;
    }
  }

  private createComponent(update: ComponentUpdate): void {
    if (!update.component) return;

    const component = this.normalizeComponent(update.component);
    const element = this.registry.render(component);
    this.components.set(component.id, component);
    this.elements.set(component.id, element);

    // Determine where to place the component
    this.positionComponent(element);
  }

  private updateComponent(update: ComponentUpdate): void {
    if (!update.component) return;

    const element = this.elements.get(update.target_id);
    if (element) {
      const component = this.normalizeComponent(update.component);
      this.registry.update(element, component, update.updates);
      this.components.set(update.target_id, component);
    }
  }

  private replaceComponent(update: ComponentUpdate): void {
    if (!update.component) return;

    const oldElement = this.elements.get(update.target_id);
    if (oldElement) {
      const component = this.normalizeComponent(update.component);
      const newElement = this.registry.render(component);
      oldElement.parentNode?.replaceChild(newElement, oldElement);

      this.elements.set(component.id, newElement);
      this.components.set(component.id, component);

      // Clean up old references if ID changed
      if (update.target_id !== component.id) {
        this.elements.delete(update.target_id);
        this.components.delete(update.target_id);
      }
    }
  }

  private removeComponent(update: ComponentUpdate): void {
    const element = this.elements.get(update.target_id);
    if (element) {
      element.remove();
      this.elements.delete(update.target_id);
      this.components.delete(update.target_id);
    }
  }

  private positionComponent(element: HTMLElement): void {
    // Always append to container
    this.container.appendChild(element);

    // Trigger scroll to bottom in parent chat component
    this.triggerScroll();
  }

  private triggerScroll(): void {
    // Find the parent vanna-chat component and trigger its scroll method
    const vannaChat = document.querySelector('vanna-chat') as any;
    if (vannaChat && typeof vannaChat.scrollToLastMessage === 'function') {
      // Use requestAnimationFrame to wait for DOM update
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          vannaChat.scrollToLastMessage();
        });
      });
    }
  }

  clear(): void {
    this.components.clear();
    this.elements.clear();
    this.container.replaceChildren();
    ensureRichComponentStyles(this.container);
  }

  getComponent(id: string): RichComponent | undefined {
    return this.components.get(id);
  }

  getAllComponents(): RichComponent[] {
    return Array.from(this.components.values());
  }

  private normalizeComponent(component: RichComponent): RichComponent {
    const data = { ...(component.data ?? {}) };

    for (const [key, value] of Object.entries(component as Record<string, any>)) {
      if (this.sharedFields.has(key) || key === 'data') continue;
      data[key] = value;
    }

    if (component.data && Object.keys(component.data).length === Object.keys(data).length) {
      return component;
    }

    return {
      ...component,
      data,
    };
  }

  private isUIStateUpdate(component: RichComponent): boolean {
    return component.type === 'status_bar_update' ||
           component.type === 'task_tracker_update' ||
           component.type === 'chat_input_update';
  }

  private processUIStateUpdate(component: RichComponent): void {
    switch (component.type) {
      case 'status_bar_update':
        this.updateStatusBar(component);
        break;
      case 'task_tracker_update':
        this.updateTaskTracker(component);
        break;
      case 'chat_input_update':
        this.updateChatInput(component);
        break;
    }
  }

  private updateStatusBar(component: RichComponent): void {
    // Find the status bar component - first try shadow DOM, then document
    let statusBar: HTMLElement | null = null;

    // Look for vanna-chat and search within its shadow root
    const vannaChat = document.querySelector('vanna-chat') as any;
    if (vannaChat && vannaChat.shadowRoot) {
      statusBar = vannaChat.shadowRoot.querySelector('vanna-status-bar') as HTMLElement | null;
    }

    // Fallback to document search
    if (!statusBar) {
      statusBar = document.querySelector('vanna-status-bar') as HTMLElement | null;
    }

    if (statusBar) {
      const { status, message, detail } = component.data || {};
      // Set properties directly on the Lit component
      (statusBar as any).status = status;
      (statusBar as any).message = message || '';
      (statusBar as any).detail = detail || '';
    }
  }

  private updateTaskTracker(component: RichComponent): void {
    // Find the progress tracker component - first try shadow DOM, then document
    let progressTracker = null;

    // Look for vanna-chat and search within its shadow root
    const vannaChat = document.querySelector('vanna-chat') as any;
    if (vannaChat && vannaChat.shadowRoot) {
      progressTracker = vannaChat.shadowRoot.querySelector('vanna-progress-tracker');
    }

    // Fallback to document search
    if (!progressTracker) {
      progressTracker = document.querySelector('vanna-progress-tracker');
    }

    if (!progressTracker) return;

    const { operation, task, task_id, status, detail } = component.data || {};

    switch (operation) {
      case 'add_task':
        if (task && progressTracker.addItem) {
          // Use the backend task ID instead of generating a new one
          progressTracker.addItem(task.title || task.text, task.description || task.detail, task.id);
        }
        break;
      case 'update_task':
        if (task_id && progressTracker.updateItem) {
          progressTracker.updateItem(task_id, status, detail);
        }
        break;
      case 'remove_task':
        if (task_id && progressTracker.removeItem) {
          progressTracker.removeItem(task_id);
        }
        break;
      case 'clear_tasks':
        if (progressTracker.clear) {
          progressTracker.clear();
        }
        break;
    }
  }

  private updateChatInput(component: RichComponent): void {
    // Find the chat input element - first try shadow DOM, then document
    let chatInput = null;

    // Look for vanna-chat and search within its shadow root
    const vannaChat = document.querySelector('vanna-chat') as any;
    if (vannaChat && vannaChat.shadowRoot) {
      chatInput = vannaChat.shadowRoot.querySelector(
        'sp-textfield.message-input, textarea.message-input, input.message-input',
      );
    }

    // Fallback to document search with multiple selectors
    if (!chatInput) {
      chatInput = document.querySelector(
        'sp-textfield.message-input, textarea[data-testid="message-input"], input[type="text"].message-input, .message-input input, .message-input textarea',
      );
    }

    if (!chatInput) return;

    const { placeholder, disabled, value, focus } = component.data || {};

    if (placeholder !== undefined) {
      chatInput.placeholder = placeholder;
    }
    if (disabled !== undefined) {
      chatInput.disabled = disabled;
    }
    if (value !== undefined) {
      chatInput.value = value;
    }
    if (focus !== undefined) {
      if (focus) {
        chatInput.focus();
      } else {
        chatInput.blur();
      }
    }
  }
}
