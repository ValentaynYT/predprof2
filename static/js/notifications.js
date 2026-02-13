// static/js/notifications.js
class NotificationsManager {
    constructor() {
        this.pollInterval = 30000; // 30 секунд
        this.lastCheck = null;
        this.dropdownOpen = false;
        this.init();
    }

    init() {
        // Инициализация кнопки уведомлений
        this.bellButton = document.getElementById('notifications-bell');
        this.dropdownMenu = document.getElementById('notifications-dropdown-menu');
        this.badge = document.getElementById('notifications-badge');

        if (this.bellButton) {
            this.bellButton.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleDropdown();
            });

            // Закрытие при клике вне
            document.addEventListener('click', (e) => {
                if (this.dropdownOpen && !this.dropdownMenu.contains(e.target) && e.target !== this.bellButton) {
                    this.closeDropdown();
                }
            });

            // Загрузка уведомлений
            this.loadNotifications();
            // Поллинг
            setInterval(() => this.checkForUpdates(), this.pollInterval);

            // Добавляем стили один раз при инициализации
            this.addStyles();
        }
    }

    addStyles() {
        // Проверяем, есть ли уже стили
        if (document.getElementById('notifications-styles')) {
            return;
        }

        const style = document.createElement('style');
        style.id = 'notifications-styles';
        style.textContent = `
            .notification-item {
                position: relative;
            }

            .notification-item-delete {
                position: absolute;
                right: 12px;
                top: 50%;
                transform: translateY(-50%);
                background: #e74c3c;
                color: white;
                border: none;
                border-radius: 50%;
                width: 24px;
                height: 24px;
                font-size: 14px;
                cursor: pointer;
                opacity: 0;
                transition: all 0.2s;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10;
            }

            .notification-item:hover .notification-item-delete {
                opacity: 1;
            }

            .notification-item-delete:hover {
                background: #c0392b;
                transform: translateY(-50%) scale(1.1);
            }
        `;
        document.head.appendChild(style);
    }

    toggleDropdown() {
        if (this.dropdownOpen) {
            this.closeDropdown();
        } else {
            this.openDropdown();
        }
    }

    openDropdown() {
        this.dropdownMenu.classList.add('show');
        this.dropdownOpen = true;
        // Загружаем уведомления при открытии
        this.loadNotifications();
        // Отмечаем как прочитанные при открытии
        this.markAllRead();
    }

    closeDropdown() {
        this.dropdownMenu.classList.remove('show');
        this.dropdownOpen = false;
    }

    async loadNotifications() {
        try {
            const response = await fetch('/api/notifications?limit=10');
            const data = await response.json();
            this.updateBadge(data.unread_count);
            this.renderNotifications(data.notifications);
        } catch (error) {
            console.error('Ошибка загрузки уведомлений:', error);
        }
    }

    renderNotifications(notifications) {
        const container = document.getElementById('notifications-list');
        if (!container) return;

        if (notifications.length === 0) {
            container.innerHTML = `
                <div class="notifications-empty">
                    <div class="notifications-empty-icon">📭</div>
                    <p>Нет новых уведомлений</p>
                </div>
            `;
            return;
        }

        container.innerHTML = notifications.map(notif => `
            <div class="notification-item ${notif.is_read ? '' : 'unread'}"
                 onclick="window.location.href='/notifications'"
                 data-id="${notif.id}">
                <div class="notification-item-icon">
                    ${this.getIcon(notif.type)}
                </div>
                <div class="notification-item-content">
                    <div class="notification-item-title">${notif.title}</div>
                    <div class="notification-item-message">${notif.message}</div>
                    <div class="notification-item-time">${notif.created_at}</div>
                </div>
                <button class="notification-item-delete"
                        onclick="event.stopPropagation(); notificationsManager.deleteNotification(${notif.id});"
                        title="Удалить">
                    ✕
                </button>
            </div>
        `).join('');
    }

    getIcon(type) {
        switch(type) {
            case 'success': return '✅';
            case 'warning': return '⚠️';
            case 'error': return '❌';
            default: return 'ℹ️';
        }
    }

    updateBadge(count) {
        if (this.badge) {
            if (count > 0) {
                this.badge.textContent = count > 99 ? '99+' : count;
                this.badge.style.display = 'inline-block';
            } else {
                this.badge.style.display = 'none';
            }
        }
    }

    async markAllRead() {
        try {
            await fetch('/api/notifications/read-all', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            // Обновляем бейдж
            this.updateBadge(0);

            // Обновляем список
            this.loadNotifications();
        } catch (error) {
            console.error('Ошибка при отметке уведомлений:', error);
        }
    }

    async deleteNotification(notificationId) {
        try {
            const response = await fetch(`/api/notifications/${notificationId}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            if (data.success) {
                // Удаляем элемент из интерфейса
                const item = document.querySelector(`.notification-item[data-id="${notificationId}"]`);
                if (item) {
                    item.style.opacity = '0';
                    item.style.transform = 'translateX(100%)';
                    setTimeout(() => {
                        item.remove();
                        // Перезагружаем список
                        this.loadNotifications();
                    }, 300);
                }
            }
        } catch (error) {
            console.error('Ошибка при удалении уведомления:', error);
        }
    }

    async checkForUpdates() {
        try {
            const response = await fetch('/api/notifications/count');
            const data = await response.json();
            // Если количество изменилось, перезагружаем
            if (this.lastCheck !== null && data.count !== this.lastCheck) {
                this.loadNotifications();
            }
            this.lastCheck = data.count;
            this.updateBadge(data.count);
        } catch (error) {
            console.error('Ошибка проверки обновлений:', error);
        }
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    window.notificationsManager = new NotificationsManager();
});