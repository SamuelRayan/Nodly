// Make localhost:8000 (API) and localhost:8081 (Metro) on every connected Android device
// (emulators and USB phones) reach this computer. Re-run after a device (re)connects or boots.
// With this, EXPO_PUBLIC_API_URL=http://localhost:8000 works on all of them at once.
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';

const sdk = process.env.ANDROID_HOME ?? join(process.env.LOCALAPPDATA ?? '', 'Android', 'Sdk');
const adb = process.platform === 'win32' ? join(sdk, 'platform-tools', 'adb.exe') : 'adb';
const ports = [8000, 8081];

const devices = execFileSync(adb, ['devices'], { encoding: 'utf8' })
  .split(/\r?\n/)
  .slice(1)
  .map((line) => line.trim().split(/\s+/))
  .filter(([serial, state]) => serial && state === 'device')
  .map(([serial]) => serial);

if (devices.length === 0) {
  console.error('No Android devices connected (start an emulator or plug in a phone).');
  process.exit(1);
}
for (const serial of devices) {
  for (const port of ports) {
    execFileSync(adb, ['-s', serial, 'reverse', `tcp:${port}`, `tcp:${port}`]);
  }
  console.log(`${serial}: localhost:${ports.join(', localhost:')} -> this computer`);
}
