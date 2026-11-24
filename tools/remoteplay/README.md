# Remote Play host: исследовательский прототип

Цель: ПК с Apollo обслуживает неизменённые штатные клиенты PS5 (профиль
сервера PS4) и PS4 (профиль сервера PS5). По приоритету пользователя сначала
получаем работающий стрим в Chiaki-ng, затем проверяем настоящие консоли.

## Реализовано

- Discovery PS4/PS5: UDP 987 / 9302; поиск регистрации SRC2/RES2 и SRC3/RES3: UDP 9295.
- Регистрация по временному PIN на TCP 9295, зашифрованный ответ, постоянные ключи.
- Session init: проверка RegistKey, новый nonce, согласование RP-Version.
- Control: проверка зашифрованных полей, session ID, независимые счётчики шифрования,
  heartbeat, освобождение сессии при разрыве. Команда rest mode только завершает
  соединение, не выключает ПК.
- Senkusha на UDP 9297: согласование протокола, RTT echo, двусторонняя проверка MTU.
- Takion на UDP 9296: INIT/COOKIE, сборка фрагментов, подтверждения и ограниченные
  повторные отправки управляющих сообщений, BIG/BANG, secp256k1 ECDH и HMAC,
  STREAMINFO, GKCrypt/GMAC для потоковых пакетов.
- Тестовая анимация 1280×720, 60 fps, H.264 SDR и тон 440 Гц, Opus stereo 48 кГц,
  10 мс/пакет. Закодированные данные передаются без перекодирования транспорта.
- Видео FEC: одна дополнительная Cauchy-паритетная часть на кадр, GF(2^8).
- Аутентифицированные кнопки/стики: расшифровка, защита от повторов sequence,
  нормализованное состояние контроллера, сброс после таймаута/отключения.

По умолчанию используется тестовый источник. Добавлен выбираемый адаптер Apollo:
GameStream pairing/HTTPS control, native Moonlight transport, передача H.264 без
перекодирования, преобразование Opus в 10-мс пакеты и отправка геймпада в Apollo.
**Соединение с настоящим Apollo ещё не проверено:** в облачном окружении нет
запущенного Apollo и доступа к игровому ПК. GUI Chiaki и физические консоли тоже
ещё не проверены.
Сборка/установщик основного Apollo не менялись. Один активный стрим одновременно;
оба профиля доступны для последовательного подключения.

## Проверки

`tests/registration_client.c` вызывает неизменённые функции регистрации Chiaki.
`tests/session_client.c` запускает его полный неизменённый движок сессии и сохраняет
данные из настоящих video/audio callbacks. Клиентские исходники не патчатся.

`session_integration.py stream` проверяет оба профиля, по два подключения:

1. Настоящая регистрация по UDP/TCP.
2. Перезапуск host и закрытие окна pairing; ключи загружаются с диска.
3. Авторизация, Senkusha и полная потоковая сессия.
4. Получение 119 видеокадров (+ callback заголовка) и около 198 аудиопакетов.
5. Побайтное сравнение видеокадров с источником и декодирование FFmpeg с `-xerror`.
6. Декодирование Opus через libopus, проверка 480 samples/packet и уровня сигнала.
7. Движение левого стика, нажатие и отпускание Cross с клиента; проверка на сервере.
8. Проверка освобождения сессии и повторный вход.

`--loss` намеренно теряет одну исходную видеочасть в каждом десятом кадре.
Побайтное совпадение после восстановления проверяет совместимость FEC с Chiaki.
`--soak` увеличивает тест до 3600 callbacks (~60 секунд) на каждый профиль.
Это loopback-тест, а не оценка качества Wi-Fi или часовая аппаратная приёмка.

Unit-тесты дополнительно покрывают неверные ключи/PIN, устаревший nonce,
неверный peer, replay, истечение pairing, framing, malformed discovery и reset ввода.

## Сборка и запуск (Linux)

Инструкции Windows и текущий статус локальной проверки: [WINDOWS.md](WINDOWS.md).

Нужны Python >=3.11, C/C++ compiler, CMake, OpenSSL headers, FFmpeg с libx264,
libopus, protoc, json-c/libevent/miniupnpc development packages и libcurl с WebSocket.
В текущем окружении проверены Python 3.12, protobuf 7.36.2, cryptography 50.0.0.

Из корня Apollo, исходники Chiaki расположены рядом:

```sh
git clone https://github.com/chiaki-ng/chiaki-ng.git ../chiaki-ng
git -C ../chiaki-ng checkout 43728af2e639fecb8a7af1cd68c29820a40de973
git -C ../chiaki-ng submodule update --init third-party/nanopb third-party/jerasure third-party/gf-complete
python -m pip install -r tools/remoteplay/requirements.txt
python tools/remoteplay/build_session.py ../chiaki-ng
python -m unittest discover -s tools/remoteplay/tests -v
python tools/remoteplay/tests/integration.py
python tools/remoteplay/tests/session_integration.py stream --loss
python tools/remoteplay/host.py --bind 127.0.0.1
```

Для отдельно распакованных библиотек сборщик принимает `--prefix /path/to/usr`.
В облачном стенде это `/workspace/deps/sysroot/usr`. Они не устанавливаются в ОС.
Сборщик проверяет commit Chiaki, собирает crypto bridge, клиентские драйверы,
полную библиотеку Chiaki и Python protobuf bindings. Полная GUI-сборка не нужна.

Тесты занимают UDP/TCP 9295 и UDP 9296/9297 на loopback. Остановить другой
прототип перед запуском. Тесты используют временные ключи и не меняют state.json.

Для внешнего Chiaki запустить host с `--bind <LAN-IP-ПК>` и разрешить входящие
UDP 987, 9302, 9295–9297 и TCP 9295 в локальном firewall. UDP 987 может требовать
дополнительных прав ОС. Использовать PIN из терминала и Account ID в клиенте;
выбрать PS4 >=8 либо PS5, H.264, 720p60, SDR. Сервер пока использует фиксированный
тестовый профиль 720p60. Облачный экземпляр не находится автоматически в домашней LAN.

PIN генерируется при запуске и действует 300 секунд. После пяти неуспешных
проверок с одного IP регистрация с него блокируется до перезапуска. state.json
содержит секреты, создаётся с правами 0600 и исключён из Git. Не публиковать его.
Логи host содержат метаданные, не ключи или Account ID. Лабораторный IPv4-сервер
не предназначен для интернета; идентичности профилей не являются идентичностями PSN.

## Адаптер Apollo (экспериментальный)

Адаптер работает отдельным процессом на ПК. Он подключается к существующему Apollo
как клиент Moonlight, а консоли видят сервер Remote Play. На консолях ничего менять
не нужно. Системный Apollo пока не переустанавливается.

```sh
git submodule update --init --recursive third-party/moonlight-common-c
python tools/remoteplay/build_moon.py
python tools/remoteplay/apollo_control.py pair 127.0.0.1
# Ввести показанный четырёхзначный PIN в UI Apollo.
python tools/remoteplay/apollo_control.py apps
python tools/remoteplay/host.py --bind <LAN-IP> \
  --apollo-state tools/remoteplay/build/apollo --apollo-app <ID-из-списка>
```

Этот путь пока собирается на Linux. `--apollo-app` явно выбирает приложение;
адаптер откажется заменять другое уже запущенное приложение. При выходе он
отключает транспорт и отпускает кнопки, но не завершает приложение Apollo.
Поток Apollo запускается вместе с host, до подключения Remote Play; запуск по
требованию и остановка захвата после последнего клиента остаются дальнейшей работой.

При привязке проверяются PIN challenge, подпись секрета и сертификат сервера;
после этого каждый HTTPS-запрос проверяет сохранённый сертификат до отправки
параметров. Ключ клиента и состояние лежат в закрытой директории build/apollo.
Четырёхзначный PIN Apollo и восьмизначный PIN Remote Play — разные привязки.

Видео: ограниченная очередь из трёх кадров, восстановление через запрос IDR при
переполнении, ожидание первого IDR перед STREAMINFO. Звук декодируется и кодируется
заново, так как длительности Opus у Apollo и Remote Play могут различаться.
Стики, D-pad, основные кнопки и триггеры сопоставлены с GameStream; Y инвертируется.
Touch contacts, motion и обратная вибрация пока не перенаправляются.

Проверки адаптера:

```sh
python -m unittest discover -s tools/remoteplay/tests -v
python tools/remoteplay/tests/session_integration.py stream --loss --live-fixture
```

15 unit-тестов проходят. Потоковый fixture подаёт paced H.264/Opus в те же callbacks,
очереди и аудиоконвертер, затем настоящий движок Chiaki получает оба профиля по два
раза, с потерями и проверкой содержимого/декодирования. Проверяется также выходное
состояние геймпада. **Fixture не является настоящим Apollo и не проверяет его
RTSP/RTP-соединение.** Библиотека Moonlight и native bridge успешно собраны с `-Werror`.
Обычный тестовый источник отдельно прошёл 60 секунд на каждый профиль с потерями:
3599 побайтно совпавших видеокадров и 5998 декодированных Opus-пакетов на профиль.

## Что осталось

1. Проверить написанный адаптер на настоящем Apollo: pairing → launch → RTSP/RTP
   → Chiaki, захват рабочего стола и ввод в игре. Нужен доступ к машине Apollo.
2. Адаптивный битрейт, измерение live pacing, поддержка размеров
   кадров больше одного FEC-блока, аудиоредундантность, длительные тесты с reorder/loss.
3. Установщик/Windows build и UI привязки в Apollo. Python здесь исследовательская
   реализация протокола; окончательный транспорт требует решения по интеграции.
4. Неизменённый GUI Chiaki, затем штатные PS5→PS4 и PS4→PS5. Настоящая PS4 у
   пользователя есть, аппаратные проверки отложены по его указанию.
5. Час игры по Ethernet, измерение задержки/AV-sync/frame pacing и аппаратных энкодеров.
6. PSN/WAN, HDR, дополнительные контроллеры, сенсоры и advanced haptics — позже.

Ограничения: 32-битный wire key position пока без поддержки wrap для очень длинных
сессий; один активный клиент; старые PS4 RP 8/9 не поддерживаются; нет PSN holepunch.
RP-KeyType=2 принят клиентом регистрации и проверен последующим входом Chiaki,
но не проверен штатным клиентом Sony. Настоящий PSN/console authentication остаётся
отдельной неизвестной. Автоматические тесты не доказывают совместимость с Sony.

## Источники и лицензии

Apollo base adc5c5a0bd80831ce495434bb16aee2cd4175fb8;
Chiaki-ng 43728af2e639fecb8a7af1cd68c29820a40de973.

Chiaki lib/src/discovery.c, regist.c, session.c, ctrl.c, senkusha.c, takion.c,
streamconnection.c, gkcrypt.c, feedback.c, frameprocessor.c, audio.c и takion.proto
определяют клиентские ожидания. LAN aeropause обращается отдельно:
upstream ambassador_from_aeropause обращает PSN-вариант, а не LAN-вариант.
Apollo src/video.h, audio.h, input.cpp, stream.cpp — точки будущей интеграции.

Прототип использует внешний Chiaki-ng под LicenseRef-AGPL-3.0-only-OpenSSL
(см. COPYING/ LICENSES в зафиксированном checkout). Бинарники bridge и тестового
клиента включают этот код. Apollo — GPL-3.0. До распространения объединённой
сборки оформить полный комплект лицензий/исходников и условия зависимостей.
Отдельный исследовательский процесс пока не включён в установщик Apollo.

Moonlight adapter: pinned c999436858471dfefa7617af3b7dc03ec1644ce4 из submodule Apollo;
см. third-party/moonlight-common-c/LICENSE.txt. Он не требует изменений протокола Apollo.
