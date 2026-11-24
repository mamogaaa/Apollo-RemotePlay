# Windows: сборка и локальная проверка

## Подтверждённый статус, 25 ноября 2026

Проверено на Windows 11 Pro x64 (26100), DESKTOP-RBF3MM2, Python 3.13.2.
Рабочий репозиторий: `C:\Users\maksi\Documents\Codex\Apollo-RemotePlay-dev\Apollo-git`.
Исходный архив отдельно распакован в соседнюю `Apollo-remoteplay`.
История восстановлена от `adc5c5a0bd80831ce495434bb16aee2cd4175fb8`
через три коммита приложенного patch. Хеши восстановленных коммитов отличаются.

- MSYS2 UCRT64, GCC 16.2, CMake 4.5.1, OpenSSL 4.1, Opus 1.6.1.
- Собраны `rpcrypt.dll`, `moonbridge.dll` и оба тестовых клиента Windows.
- Внешние исходники Chiaki и Moonlight не изменены.
- 15 unit-тестов прошли, включая Windows ACL для ключей и состояния.
- Неизменённый движок Chiaki: регистрация обоих профилей, отклонение неверного PIN,
  H.264/Opus с тестовым источником, передача кнопок/стика, по два подключения
  к каждому профилю с намеренной потерей видеочастей — успешно.
- Официальный GUI Chiaki-ng 1.10.1 распакован в соседнюю `Chiaki-official`
  и запущен. Это пока только проверка запуска, не сквозной тест GUI.
- Системный Apollo работает как `ApolloService` в `C:\Program Files\Apollo`.
  Реальная привязка/захват пока не выполнены: локальный веб-интерфейс требует входа.

**Первый этап НЕ завершён:** тестовые источники не подтверждают видео, звук и
управление от настоящего Apollo. Физические консоли не тестировались.

## Зависимости

Установить MSYS2 (`winget install -e --id MSYS2.MSYS2`). В MSYS2 выполнить
`pacman -Syu --noconfirm`, перезапустить оболочку после обновления runtime,
повторить обновление. Затем:

```sh
pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-cmake \
  mingw-w64-ucrt-x86_64-ninja mingw-w64-ucrt-x86_64-openssl \
  mingw-w64-ucrt-x86_64-opus mingw-w64-ucrt-x86_64-protobuf \
  mingw-w64-ucrt-x86_64-json-c mingw-w64-ucrt-x86_64-libevent \
  mingw-w64-ucrt-x86_64-miniupnpc mingw-w64-ucrt-x86_64-curl
```

При проблемах загрузки зеркала можно скачать URL из `pacman -Sp` через
PowerShell в кеш pacman вместе с `.sig`, затем повторить установку.
Проверку подписей отключать не требуется.

Нужны Git, Windows Python >=3.11, FFmpeg для проверок медиа и PowerShell 7
для проверки ACL в тестах. Команды далее выполняются из корня Apollo:

```powershell
git submodule update --init --recursive third-party/moonlight-common-c
git clone https://github.com/chiaki-ng/chiaki-ng.git ../chiaki-ng
git -C ../chiaki-ng checkout 43728af2e639fecb8a7af1cd68c29820a40de973
git -C ../chiaki-ng submodule update --init third-party/nanopb third-party/jerasure third-party/gf-complete
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools/remoteplay/requirements.txt
.\.venv\Scripts\python.exe tools/remoteplay/build_windows.py ../chiaki-ng --clients
$env:PATH = 'C:\msys64\ucrt64\bin;' + $env:PATH
.\.venv\Scripts\python.exe -m unittest discover -s tools/remoteplay/tests -v
.\.venv\Scripts\python.exe tools/remoteplay/tests/integration.py
.\.venv\Scripts\python.exe tools/remoteplay/tests/session_integration.py stream --loss
```

`--clients` необязателен для самого host. `--prefix` меняет путь UCRT64 при сборке;
`REMOTEPLAY_NATIVE_BIN` указывает его `bin` при запуске, если установлен не в
`C:\msys64\ucrt64`. Python использует явные DLL directories, а дочерние тестовые
EXE требуют UCRT64 `bin` в PATH. MSYS2 здесь лишь инструменты: все исполняемые
файлы и Python работают локально на Windows, без WSL/Linux.

## Настоящий Apollo

1. Войти в локальную панель `https://localhost:47990/pin`.
2. Запустить привязку и ввести показанный четырёхзначный PIN в панели Apollo:

```powershell
.\.venv\Scripts\python.exe tools/remoteplay/apollo_control.py pair 127.0.0.1
.\.venv\Scripts\python.exe tools/remoteplay/apollo_control.py apps
```

3. Выбрать ID Desktop из результата, запустить (заменить `<Desktop-ID>`):

```powershell
.\.venv\Scripts\python.exe tools/remoteplay/host.py --bind 127.0.0.1 --apollo-state tools/remoteplay/build/apollo --apollo-app <Desktop-ID>
```

4. В неизменённом Chiaki-ng добавить вручную `127.0.0.1`, выбрать PS4 >=8 либо
   PS5, указать Account ID и восьмизначный PIN host. Для локального прототипа
   допускается лабораторный восьмибайтовый Account ID `QkJCQkJCQkI=`;
   он не является авторизацией PSN. Видео: H.264, 720p60, SDR.
5. Подтвердить движущийся рабочий стол/игру, звук, действие геймпада в приложении
   и повторное подключение отдельно для обоих профилей. Только это завершает этап.

Loopback не требует расширять правила firewall. Не подключать лабораторный host
к интернету. Для отдельного устройства позднее явно выбрать LAN IP и правила.

## Исправления Windows

- CMake собирает native DLL с экспортами C ABI и зависимостями Winsock/WinMM.
- Выровненная память использует `_aligned_malloc/_aligned_free`.
- DLL загружаются из явных путей; Opus — `libopus-0.dll`.
- Секреты получают защищённую DACL до записи содержимого: текущий пользователь,
  SYSTEM и Administrators. Unix mode bits на Windows недостаточно.
- UDP listeners отключают `SIO_UDP_CONNRESET`: ICMP после закрытия клиентского
  порта иначе останавливает приём asyncio Proactor и ломает повторный вход.
- Тестовые драйверы вызывают WSAStartup, используют Winsock и Sleep.

## Откат и секреты

Исходная конфигурация Apollo частично скопирована в `work/apollo-backup/config`
(каталог исключён из Git). `credentials/cacert.pem` и `credentials/cakey.pem`
не удалось скопировать из-за ACL службы. **Это неполная резервная копия.**
До замены установленного Apollo нужно получить административный доступ и
сохранить также эти файлы. Сейчас служба и её конфигурация не заменялись.

Не добавлять в Git `build/apollo`, `state.json`, резервные копии, клиентские логи
с ключами или дампы. По умолчанию эти локальные данные исключены.
