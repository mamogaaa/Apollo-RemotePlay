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
- 17 unit-тестов прошли, включая Windows ACL и обработку тишины.
- Неизменённый движок Chiaki: регистрация, тестовые медиа с потерями и повторный вход — успешно.
- Настоящий Apollo v0.3.0 → адаптер → официальный GUI Chiaki-ng 1.10.1:
  оба профиля PS4/PS5 подключены и переподключены; виден живой рабочий стол,
  Cross и D-pad управляют отдельным Windows-приложением через XInput.
- Звук GUI проверен через Windows audio session на физическом выходе Mi Monitor:
  peak 0.088–0.098, mute=0; запись loopback этого выхода содержит сигнал
  RMS 0.0602, peak 0.0963. Это измерение реального вывода клиента, не субъективная
  оценка громкости/качества встроенных динамиков.
- После закрытия звучащего приложения видео продолжает работать более 12 секунд.
- Дополнительный реальный headless-тест: четыре сессии (по две на профиль),
  по 119 декодированных кадров, 286–364 аудиопакета, RMS PCM 1957–1972.
- Системный Apollo работает как ApolloService. Привязка и доступ настроены,
  конфигурация полностью сохранена перед изменениями.

Первый этап проверен на этом Windows-ПК с официальным Chiaki GUI.
Физические консоли и штатные Sony Remote Play клиенты пока НЕ проверены.
Один активный стрим; H.264 SDR 720p60. Это исследовательский прототип.

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

На этом ПК привязка уже сохранена; повторять её не нужно. Для новой установки:

1. Войти в локальную панель `https://localhost:47990/pin`.
2. Запустить привязку и ввести показанный четырёхзначный PIN в панели Apollo:

```powershell
.\.venv\Scripts\python.exe tools/remoteplay/apollo_control.py pair 127.0.0.1
.\.venv\Scripts\python.exe tools/remoteplay/apollo_control.py apps
```

3. Выбрать ID Desktop из результата (на этом ПК `881448767`), запустить:

```powershell
.\.venv\Scripts\python.exe tools/remoteplay/host.py --bind 127.0.0.1 --apollo-state tools/remoteplay/build/apollo --apollo-app 881448767
```

Перед GUI можно отдельно проверить транспорт настоящего источника:

```powershell
.\.venv\Scripts\python.exe tools/remoteplay/tests/session_integration.py stream --apollo-state tools/remoteplay/build/apollo --apollo-app 881448767
```

Этот тест регистрирует временные клиентские ключи и выполняет по два соединения
для каждого профиля. Полученные H.264, Opus-пакеты и декодированный WAV остаются
в закрытом от Git каталоге `tools/remoteplay/build`. FFmpeg проверяет видео,
libopus — длительность аудиопакетов; уровень сигнала печатается отдельно.
Тишина помечается явно и не считается подтверждением слышимого звука.
Этот тест не заменяет проверку GUI и реакции реального приложения на ввод.
Не запускать тест и `host.py` одновременно: они занимают одинаковые порты.

4. В неизменённом Chiaki-ng добавить вручную `127.0.0.1`, выбрать PS4 >=8 либо
   PS5, указать Account ID и восьмизначный PIN host. Для локального прототипа
   допускается лабораторный восьмибайтовый Account ID `QkJCQkJCQkI=`;
   он не является авторизацией PSN. Видео: H.264, 720p60, SDR.
5. Проверить движущийся рабочий стол, звук, ввод и повторное подключение обоих
   профилей. На данном ПК это выполнено; при переносе повторить проверку.

### Chiaki на том же ПК

Используется отдельный профиль `ApolloRemotePlayLab`, в нём уже зарегистрированы
Apollo-RP-PS4 и Apollo-RP-PS5. Оба адреса — 127.0.0.1. Официальный EXE:
`../Chiaki-official/chiaki-ng-Win/chiaki.exe`.

```powershell
$env:SDL_GAMECONTROLLER_IGNORE_DEVICES = '0x045e/0x028e'
$env:SDL_XINPUT_ENABLED = '0'
& ../Chiaki-official/chiaki-ng-Win/chiaki.exe --profile ApolloRemotePlayLab --opengl
```

Эти переменные относятся только к лаборатории на одном ПК: исключают повторное
чтение виртуального Xbox, который сам Apollo создаёт для удалённого ввода.
Управление клавиатурой Chiaki: Enter = Cross, стрелки = D-pad. F11 меняет
полноэкранный режим. При отключении выбрать No, чтобы не посылать rest mode.

В настройках **Local и Remote PS5** установить H.264, 720p, 60 fps, SDR.
Chiaki 1.10.1 классифицирует loopback как Remote, поэтому одного Local недостаточно.
Вывод аудио Chiaki: Mi Monitor (NVIDIA High Definition Audio), отдельно от
Speakers (Steam Streaming Speakers), который захватывает Apollo. Иначе получается
аудиопетля. На другом клиентском устройстве эта изоляция не нужна.

Apollo `dd_configuration_option=ensure_active` сохраняет физические экраны.
При необходимости `DisplaySwitch.exe /extend` восстанавливает расширенный стол.
Окно Chiaki должно находиться на физическом экране, вне виртуального захвата Apollo.
Проверочное приложение `python tools/remoteplay/tests/desktop_probe.py` разместить
на захватываемом экране: оно рисует часы, воспроизводит системный звук и читает
реальный XInput. Закрытие окна останавливает звук. Это не источник медиа адаптера.

Клиенту Apollo Remote Play adapter нужны Launch Apps и Controller Input в панели
Apollo. Они уже включены. PIN привязки Apollo и восьмизначный PIN host — разные.

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
- WASAPI может не выдавать аудио при тишине. Ожидание аудио теперь не обрывает
  видео через 10 секунд; ошибки транспорта по-прежнему завершают поток.

## Откат и секреты

Полная резервная копия, включая credentials, создана с административным доступом:
`work/apollo-full-backup-20261125-085048/config` (защищённая ACL, вне Git).
Изменены пароль панели, привязка адаптера/его разрешения и
`dd_configuration_option` с ensure_only_display на ensure_active.
Бинарники установленного Apollo не заменялись.

Для отката из повышенного PowerShell остановить ApolloService, восстановить файлы
из этой копии в `C:\Program Files\Apollo\config`, запустить службу. Это также
вернёт прежние пароль/список привязок. Новый пароль сохранён локально через DPAPI
в `work/apollo-admin.credential.xml`, расшифровывается только этим Windows-пользователем.
Не переносить credential или резервные копии в отчёты.

Не добавлять в Git `build/apollo`, `state.json`, резервные копии, клиентские логи
с ключами или дампы. По умолчанию эти локальные данные исключены.
