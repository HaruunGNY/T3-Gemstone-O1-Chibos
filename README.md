# T3 Gemstone O1 — ArduCopter on ChibiOS (MCU R5F)

Gerçek ArduCopter'ı, T3 Gemstone O1 kartının Linux/A53 çekirdekleri yerine
doğrudan **MCU domain Cortex-R5F** çekirdeğinde, ChibiOS RTOS üzerinde
çalıştıran kurulum. Bu depo, 2026-08-18'de gerçek uçuşla doğrulanmış hâliyle
gereken **tüm parçaları tek bir yerde** toplar: ArduPilot kaynağı + özel HAL,
altında çalışan ChibiOS portu, ve karta/host'a kurulan tüm dağıtım (deploy)
dosyaları.

Önce **[deploy/kurulum_rehberi.txt](deploy/kurulum_rehberi.txt)** dosyasını okuyun — sıfırdan
kurulumun her adımı, ne işe yaradığı ve bilinen sorunlar/çözümleri orada.

## Bu depo neyi birleştiriyor

Aslen ayrı iki depo olan şu ikisi, orijinal (2026-08-18, uçan) kaynak
haliyle burada tek repo olarak birleştirildi:

- **ArduPilot fork** — [emirhan-sonmez/ardupilot](https://github.com/emirhan-sonmez/ardupilot),
  dal `gemstone-o1-r5f-hal`. Bu deponun kökü. Gerçek ArduCopter uygulaması +
  R5F için yazılmış özel HAL backend: [libraries/AP_HAL_ChibiOS_K3/](libraries/AP_HAL_ChibiOS_K3/).
- **ChibiOS portu** — [emirhan-sonmez/ChibiOS-Gemstone-O1-Port](https://github.com/emirhan-sonmez/ChibiOS-Gemstone-O1-Port),
  dal `gemstone-o1-r5f`. Yukarıdakinin derleme bağımlılığı; burada
  [modules/ChibiOS-Gemstone-O1-Port/](modules/ChibiOS-Gemstone-O1-Port/) altında.

İki depo, tüm katkı/orijinal geliştirme **emirhan-sonmez**'e ait. Bu repo
onları tek klasörde derlenebilir hâlde toplayan, T3 Gemstone O1 kartında
gerçekten uçuşla doğrulanmış bir anlık görüntü (snapshot).

`deploy/` altında ayrıca karta ve host makineye kurulan, kaynak
depolarının hiçbirinde bulunmayan parçalar var (bu oturumda yazıldı):
board-native parametre depolama daemon'u, host↔R5F arası paylaşımlı
bellek üzerinden MAVLink köprüsü, ve 4 systemd servis dosyası.

## Derleme

```
python3 waf configure --board GemstoneO1R5F
python3 waf copter
```

`GEMSTONE_CHIBIOS_ROOT` env var'ı ayarlamaya gerek yok — varsayılan olarak
depo içindeki `modules/ChibiOS-Gemstone-O1-Port/` kullanılır (bkz.
[Tools/ardupilotwaf/chibios_k3.py](Tools/ardupilotwaf/chibios_k3.py)).
Farklı bir ChibiOS portu denemek isterseniz env var ile override edebilirsiniz.

Çıktı: `build/GemstoneO1R5F/bin/arducopter`

## Karta kurulum / dağıtım

Tam adımlar için [deploy/kurulum_rehberi.txt](deploy/kurulum_rehberi.txt).
Kısaca:

- [deploy/board/gem_storaged.py](deploy/board/gem_storaged.py) — kartın kendi Linux'unda çalışır,
  ArduCopter'ın paylaşımlı bellekteki parametrelerini gerçek diske kalıcı yazar.
- [deploy/host/gem_mavbridge.py](deploy/host/gem_mavbridge.py) + [deploy/host/run_bridge.py](deploy/host/run_bridge.py) —
  host makinede çalışır, R5F'in paylaşımlı bellek MAVLink halkasını
  QGroundControl için UDP 14550'ye köprüler.
- [deploy/systemd-board/](deploy/systemd-board/) — kartın kendi Linux'una kurulacak 3 servis
  (`chibios-spi-release`, `chibios-pwm-clocks`, `gem-storaged`).
- [deploy/systemd-host/gem-mavbridge.service](deploy/systemd-host/gem-mavbridge.service) — host'ta
  `systemd --user` servisi olarak kurulur.

## Bilinen kısıtlamalar (2026-08-18 itibarıyla)

- GPS çalışmıyor — GPS, R5F'in erişemediği Main-domain UART'ta. Sadece
  Stabilize/Acro gibi GPS'siz modlar kullanılabilir.
- IMU 100Hz'e sabit, bu yüzden `SCHED_LOOP_RATE=50` gerekiyor (400Hz
  varsayılanla prearm hataları veriyor).
- Her firmware değişikliğinden sonra tam board reboot gerekiyor (remoteproc
  mailbox stop handshake henüz implement edilmemiş).

Detaylar: [deploy/kurulum_rehberi.txt](deploy/kurulum_rehberi.txt) bölüm 6.

Orijinal ArduPilot projesi hakkında: [README_ARDUPILOT.md](README_ARDUPILOT.md).
