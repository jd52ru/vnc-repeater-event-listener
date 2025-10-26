# VNC Repeater Event Listener

Система для мониторинга и управления VNC соединениями через UltraVNC Repeater с веб-интерфейсом.

## Особенности

- Веб-интерфейс для мониторинга VNC соединений
- Интеграция с UltraVNC Repeater
- База данных событий в реальном времени
- Системные службы для автоматического запуска
- Поддержка noVNC для веб-доступа к VNC сессиям

## Требования

- Linux (тестировалось на RedOS8)
- Python 3.8+
- g++ компилятор
- make
- Доступ к порту 80 (для веб-интерфейса)

## Установка

### 1. Клонирование репозитория

```bash
git clone https://github.com/jd52ru/vnc-repeater-event-listener.git
cd vnc-repeater-event-listener
```

### 2. Установка необходимых пакетов

**Для RedOS:**
```bash
sudo yum update
sudo yum install -y python3 python3-venv gcc-c++ make git
```

**Проверка установленных компонентов:**
```bash
# Проверка Python
python3 --version

# Проверка компилятора
g++ --version

# Проверка make
make --version
```

### 3. Запуск установки

```bash
sudo ./scripts/install.sh
```

**Что делает установщик:**
- Создает системного пользователя 'uvncrep'
- Компилирует UltraVNC Repeater из исходного кода
- Создает виртуальное окружение Python
- Устанавливает все необходимые зависимости
- Настраивает конфигурационные файлы
- Создает и запускает системные службы
- Настраивает права доступа и безопасность

**Во время установки вас спросят:**
- Подтверждение создания системного пользователя
- Разрешение на использование порта 80

## Доступ к веб-интерфейсу

После успешной установки откройте в браузере:
```
http://ваш-сервер-ip
```

**Веб-интерфейс включает:**
- 📊 Дашборд с общей статистикой
- 🔄 Мониторинг активных VNC соединений
- 📝 Просмотр истории событий
- 🖥️ Встроенный noVNC клиент для подключения к сессиям

## Управление службами

### Event Listener (Веб-интерфейс)

```bash
# Запуск службы
sudo systemctl start uvnc-event-listener

# Остановка службы
sudo systemctl stop uvnc-event-listener

# Статус службы
sudo systemctl status uvnc-event-listener

# Включение автозапуска
sudo systemctl enable uvnc-event-listener

# Отключение автозапуска
sudo systemctl disable uvnc-event-listener

# Просмотр логов в реальном времени
sudo journalctl -u uvnc-event-listener -f

# Просмотр последних логов
sudo journalctl -u uvnc-event-listener -n 50
```

### UltraVNC Repeater

```bash
# Запуск службы
sudo systemctl start uvncrepeater

# Остановка службы
sudo systemctl stop uvncrepeater

# Статус службы
sudo systemctl status uvncrepeater

# Включение автозапуска
sudo systemctl enable uvncrepeater

# Отключение автозапуска
sudo systemctl disable uvncrepeater

# Просмотр логов в реальном времени
sudo journalctl -u uvncrepeater -f

# Просмотр последних логов
sudo journalctl -u uvncrepeater -n 50
```

## Удаление

Для полного удаления системы выполните:

```bash
sudo ./scripts/uninstall.sh
```

**Во время удаления вас спросят о сохранении:**
- Конфигурационных файлов в '/etc/uvnc/'
- Файлов логов в '/var/log/uvnc/'
- Базы данных в '/tmp/'
- Системного пользователя 'uvncrep'
- Виртуального окружения Python
- Файлов проекта

**Быстрое удаление (без запросов):**
```bash
sudo ./scripts/uninstall.sh <<< $'y\ny\ny\ny\ny\ny\n'
```

## Безопасность

### Меры безопасности, реализованные в системе:

**1. Изоляция процессов:**
- Обе службы работают под непривилегированным пользователем 'uvncrep'
- Используются namespaces и private tmp

**2. Ограничение прав:**
- Event Listener использует 'CAP_NET_BIND_SERVICE' вместо полного root доступа
- Запрещено получение новых привилегий ('NoNewPrivileges=yes')
- Строгая защита системных файлов ('ProtectSystem=strict')

**3. Сетевая безопасность:**
- UltraVNC Repeater отправляет события только на localhost (127.0.0.1)
- Веб-интерфейс доступен только по HTTP (порт 80)
- Рекомендуется использовать обратный прокси с HTTPS для production

**4. Файловая система:**
- Ограничен доступ к домашним директориям ('ProtectHome=yes')
- Разрешены записи только в необходимые директории

### Рекомендации по усилению безопасности:

```bash
# Настройка брандмауэра (firewalld)
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --permanent --add-port=5500/tcp
sudo firewall-cmd --permanent --add-port=5900/tcp
sudo firewall-cmd --reload

# Или для iptables
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 5500 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 5900 -j ACCEPT
```

## Логи

### Системные логи (journalctl)

```bash
# Все логи Event Listener
sudo journalctl -u uvnc-event-listener

# Все логи UltraVNC Repeater
sudo journalctl -u uvncrepeater

# Логи за последний час
sudo journalctl -u uvnc-event-listener --since "1 hour ago"

# Логи с определенной даты
sudo journalctl -u uvncrepeater --since "2024-01-01" --until "2024-01-02"

# Логи в реальном времени
sudo journalctl -u uvnc-event-listener -f
```

## Устранение неисправностей

### Если службы не запускаются:

```bash
# Проверка статуса
sudo systemctl status uvnc-event-listener
sudo systemctl status uvncrepeater

# Подробные логи
sudo journalctl -u uvnc-event-listener -xe
sudo journalctl -u uvncrepeater -xe

# Проверка портов
sudo netstat -tlnp | grep :80
sudo netstat -tlnp | grep :5500
sudo netstat -tlnp | grep :5900
```

### Если веб-интерфейс недоступен:

```bash
# Проверка Firewall
sudo firewall-cmd --list-all

# Проверка доступности порта
curl -I http://localhost

# Проверка службы
sudo systemctl status uvnc-event-listener
```

## Конфигурация

### Основные конфигурационные файлы:

- '/etc/uvnc/uvncrepeater.ini' - конфигурация UltraVNC Repeater
- '/etc/systemd/system/uvnc-event-listener.service' - служба Event Listener
- '/etc/systemd/system/uvncrepeater.service' - служба UltraVNC Repeater

### Настройка портов:

По умолчанию используются порты:
- **80** - Веб-интерфейс Event Listener
- **5500** - UltraVNC Repeater (серверы)
- **5900** - UltraVNC Repeater (клиенты)
