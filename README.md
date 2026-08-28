<p align="center">
    <picture>
        <source media="(prefers-color-scheme: dark)" srcset=".meta/logo-dark.png" width="40%" />
        <source media="(prefers-color-scheme: light)" srcset=".meta/logo-light.png" width="40%" />
        <img alt="T3 Foundation" src=".meta/logo-light.png" width="40%" />
    </picture>
</p>

# T3 Gemstone O1 — ChibiOS Üzerinde ArduCopter

[![T3 Foundation](./.meta/t3-foundation.svg)](https://www.t3vakfi.org/en) [![License](https://img.shields.io/badge/License-GPLv3-blue.svg)](COPYING.txt)

> **Resmi olmayan, bağımsız bir çalışma.** T3 Vakfı'nın resmi bir projesi
> değildir — T3 Gemstone O1 donanımını hedefleyen, T3 ekibinden bağımsız bir
> geliştiricinin deneysel çalışmasıdır.

## Nedir?

T3 Gemstone O1 kartında ArduCopter'ı, Linux yerine kartın ayrı **R5F**
çekirdeğinde, **ChibiOS** adlı bir RTOS üzerinde çalıştıran bir kurulum. R5F,
Linux'a göre daha az gecikmeli/daha öngörülebilir zamanlama sunduğu için uçuş
kontrolü gibi zamanlamaya duyarlı işler için ilgi çekici bir alternatif.

2026-08-18'de gerçek donanımda uçuşla doğrulandı.

Depo, aslen ayrı iki proje olan şunları içinde barındırıyor (ayrıca
klonlamanıza gerek yok):

- **ArduPilot** ([emirhan-sonmez/ardupilot](https://github.com/emirhan-sonmez/ardupilot),
  dal `gemstone-o1-r5f-hal`) — bu deponun kökü, R5F'e özel HAL:
  [libraries/AP_HAL_ChibiOS_K3/](libraries/AP_HAL_ChibiOS_K3/).
- **ChibiOS portu** ([emirhan-sonmez/ChibiOS-Gemstone-O1-Port](https://github.com/emirhan-sonmez/ChibiOS-Gemstone-O1-Port),
  dal `gemstone-o1-r5f`) — [modules/ChibiOS-Gemstone-O1-Port/](modules/ChibiOS-Gemstone-O1-Port/) altında.

`deploy/` altında ise karta/host'a kurulan, bu proje için özel yazılmış
parçalar var: parametre kaydetme, MAVLink köprüsü, systemd servisleri.

## ⚠️ Güvenlik

- **Pervaneleri çıkarmadan arm/motor testi yapmayın** — bu firmware'de arm
  olduğunda motorlar gerçekten dönebilir.
- **GPS çalışmıyor** — Auto/Guided/RTL/PosHold yok, sadece Stabilize/Acro
  (bkz. [Bilinen Kısıtlamalar](#bilinen-kısıtlamalar)).
- Batarya voltaj/akım telemetrisi yok, gözle takip edin.
- İlk testler pervanesiz, tezgahta sabitlenmiş halde yapılmalı.

## Kurulum

Kart bilgileri: adres `192.168.7.2` (USB-Ethernet), kullanıcı `gemstone`,
SSH/sudo parolası `gem`.

##### 1. Host'a Gerekli Paketler

Host bilgisayarınıza (karta değil) kurun:

```bash
sudo apt update
sudo apt install -y git make python3 python3-pip sshpass ssh gcc-arm-none-eabi
pip3 install empy==3.3.4
```

##### 2. Depoyu Klonlama

```bash
git clone https://github.com/HaruunGNY/T3-Gemstone-O1-Chibos.git
cd T3-Gemstone-O1-Chibos
```

##### 3. Derleme

```bash
python3 waf configure --board GemstoneO1R5F
python3 waf copter
```

İlk çalıştırmada internet gerekir (waf kendi alt bileşenini indirir).
Derleme sonunda `build/GemstoneO1R5F/bin/arducopter` (ELF) oluşur.

## Karta İlk Deploy (Test, Kalıcı Değil)

Host'ta, derlenen dosyayı karta kopyalayın:

```bash
sshpass -p gem scp build/GemstoneO1R5F/bin/arducopter gemstone@192.168.7.2:/tmp/ap-k3.elf
```

Karta bağlanıp (`ssh gemstone@192.168.7.2`, parola `gem`) o oturumda
çalıştırın:

```bash
sudo systemctl stop arducopter
sudo sh -c 'echo 4b00000.spi > /sys/bus/platform/drivers/omap2_mcspi/unbind'
sudo cp /tmp/ap-k3.elf /lib/firmware/ap-k3.elf
sudo sh -c 'echo stop > /sys/class/remoteproc/remoteproc2/state'
sudo sh -c 'echo ap-k3.elf > /sys/class/remoteproc/remoteproc2/firmware'
sudo sh -c 'echo start > /sys/class/remoteproc/remoteproc2/state'
```

> Bu firmware remoteproc'un "durdur" el sıkışmasını (mailbox) henüz
> implement etmiyor — R5F zaten bizim firmware'imizi çalıştırıyorsa
> yukarıdaki "stop" adımı çalışmaz, önce `sudo reboot` ile kartı tam
> yeniden başlatıp tekrar bağlanmanız gerekir. **Yani her kod
> değişikliğinde: reboot → yeniden bağlan → yukarıdaki 6 komut.**

Debug çıktısı (`trace0`, 16 KB, dairesel değil):

```bash
sudo cat /sys/kernel/debug/remoteproc/remoteproc2/trace0
```

## Kalıcı Hale Getirme

Kartın her açılışında bu firmware ile gelmesi için, kartta:

```bash
sudo sh -c 'test -f /lib/firmware/j722s-mcu-r5f0_0-fw.bak || cp /lib/firmware/j722s-mcu-r5f0_0-fw /lib/firmware/j722s-mcu-r5f0_0-fw.bak'
sudo cp /tmp/ap-k3.elf /lib/firmware/j722s-mcu-r5f0_0-fw
sudo systemctl disable --now arducopter
```

Sonra aşağıdaki 3 servisi kurup kartı reboot atın.

**Geri alma** (Linux/ArduCopter'a dönmek için, kartta):

```bash
sudo cp /lib/firmware/j722s-mcu-r5f0_0-fw.bak /lib/firmware/j722s-mcu-r5f0_0-fw
sudo systemctl disable chibios-spi-release chibios-pwm-clocks gem-storaged
sudo systemctl enable arducopter
sudo reboot
```

##### 3 Kart-Üzeri systemd Servisi

Tanımları [deploy/systemd-board/](deploy/systemd-board/) altında,
`sysinit.target`'a bağlı (ağ/SSH ayağa kalkmadan önce çalışırlar):

| Servis | Ne işe yarar |
|---|---|
| `chibios-spi-release.service` | SPI0'ı Linux'tan alıp R5F'e serbest bırakır |
| `chibios-pwm-clocks.service` | Motor PWM saatlerini açar — **bu olmadan arm başarılı görünür ama motorlar dönmez** |
| `gem-storaged.service` | Kalibrasyon/parametre verisini diske yazar — **mutlaka board-native olmalı**; ArduCopter kalibrasyon verisini açılışta en fazla 60sn bekliyor, SSH'tan tetiklenen bir sürüm ağın hazır olmasını bekleyip bu pencereyi kaçırmış ve bir kez gerçek kalibrasyon verisini boş veriyle ezmişti |

Kurmak için (host'tan kopyala, kartta etkinleştir — `<dosya>` yerine servis
adını yazın):

```bash
sshpass -p gem scp deploy/systemd-board/<dosya>.service gemstone@192.168.7.2:/tmp/<dosya>.service
```

```bash
sudo cp /tmp/<dosya>.service /etc/systemd/system/<dosya>.service
sudo systemctl daemon-reload
sudo systemctl enable --now <dosya>.service
```

`gem-storaged.service` için ayrıca Python betiğini kopyalayın:

```bash
sshpass -p gem scp deploy/board/gem_storaged.py gemstone@192.168.7.2:/tmp/gem_storaged.py
```

```bash
sudo cp /tmp/gem_storaged.py /home/gemstone/gem_storaged.py
```

## Yapılandırma

IMU okuma hızı donanımsal olarak 100Hz'e sabit olduğu için, QGroundControl'de
(Vehicle Setup → Parameters) `SCHED_LOOP_RATE` parametresini **`50`** yapın —
aksi halde "Main loop slow" / "Gyro rate" hatasıyla arm edemezsiniz.

## QGroundControl Bağlantısı

ArduCopter, MAVLink'i R5F↔Linux paylaşımlı belleği (`0xA1120000`, 64 KiB)
üzerinden taşıyor; bunu UDP 14550'ye çeviren köprü host'ta çalışır
([deploy/host/](deploy/host/)):

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd-host/gem-mavbridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gem-mavbridge
loginctl enable-linger "$USER"
```

`gem-mavbridge.service`'teki `ExecStart` satırının `run_bridge.py`
dosyanızın gerçek konumuna işaret ettiğinden emin olun. Sonra
QGroundControl'ü açın — otomatik olarak UDP 14550'yi dinler ve bağlanır.

## Bilinen Kısıtlamalar

- **GPS henüz test edilmedi** — altyapı (`am67_uart6_probe`) yazılıp derlendi
  ama gerçek kartta hiç çalıştırılmadı, `serial3` hâlâ boş bir stub. Auto/
  Guided/RTL/PosHold gibi GPS gerektiren modlar kullanılamaz.
- **IMU okuma hızı 100Hz'e sabit** — `SCHED_LOOP_RATE=50` şart (bkz.
  [Yapılandırma](#yapılandırma)).
- **`ARMING_CHECK` parametresi "eksik" görünüyor** — kozmetik, QGC'nin
  dahili listesi güncel değil, arm'ı/uçuşu engellemiyor.
- **Her firmware değişikliğinde tam reboot şart** — remoteproc mailbox
  stop-handshake'i henüz implement edilmedi.
- **`trace0` debug çıktısı 16 KB, dairesel değil.**
- **Batarya voltaj/akım telemetrisi yok** — donanımsal olarak tanımlı değil.

## Sorun Giderme

**"can't stop rproc: -16" / "module-reset assert failed, ret=-19":** R5F
zaten bizim firmware'imizi çalıştırıyor, "durdur" komutuna cevap vermiyor.
Kartı reboot edin, deploy adımlarını baştan uygulayın.

**Arm oluyor ama motorlar hiç dönmüyor:** `chibios-pwm-clocks.service`
kurulu ve aktif mi kontrol edin.

**QGroundControl bağlanmıyor:** kart açık/USB-C bağlı mı, `systemctl --user
is-active gem-mavbridge` "active" mi, `remoteproc2/state` "running" mi
kontrol edin.

**Kalibrasyon/ayarlar reboot sonrası kayboluyor:** `gem-storaged.service`
board-native mi (SSH ile değil, kartın kendi systemd'i üzerinden)
çalıştığını doğrulayın.

**`/dev/mem` üzerinden okurken/yazarken "Bus error":** R5F ile paylaşılan
bellek bölgelerine erişirken başlangıç/bitiş adresi 8 byte'a hizalı olmalı —
`deploy/`'daki `read_aligned()`/`write_aligned()` fonksiyonları bunu zaten
hallediyor.

**GPS'i çalıştırmayı denemek istiyorum:** GPS'in bağlı olduğu seri port
(`UART-MAIN6`), R5F'in zaten başarıyla eriştiği başka bir portla aynı
donanım ailesinde — "R5F oraya hiç erişemez" varsayımı kesin değil, ama
henüz gerçek donanımda doğrulanmadı.

## Depo Yapısı

```
.                                  ArduPilot kaynağı (emirhan-sonmez/ardupilot @ gemstone-o1-r5f-hal)
├── libraries/AP_HAL_ChibiOS_K3/   R5F için özel HAL backend
├── modules/ChibiOS-Gemstone-O1-Port/   ChibiOS portu (emirhan-sonmez/ChibiOS-Gemstone-O1-Port @ gemstone-o1-r5f)
└── deploy/                        Karta/host'a kurulan, hiçbir kaynak repoda olmayan parçalar
    ├── board/gem_storaged.py      Kart üzerinde çalışan parametre kaydetme betiği
    ├── host/gem_mavbridge.py, run_bridge.py   Host↔kart MAVLink köprüsü
    ├── systemd-board/             3 kart-üzeri (board-native) servis tanımı
    └── systemd-host/              Host'taki systemd --user servis tanımı
```

Orijinal ArduPilot projesi hakkında genel bilgi için:
[README_ARDUPILOT.md](README_ARDUPILOT.md).
