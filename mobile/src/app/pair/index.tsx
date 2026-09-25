import { CameraView, useCameraPermissions } from 'expo-camera';
import { useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { View } from 'react-native';

import { Body, Button, ErrorNote, Field, Screen, Title } from '@/components/ui';
import { codeFromScan, usePairing } from '@/pairing/usePairing';
import { useAppStore } from '@/state/app';
import { useTheme } from '@/theme';

/** Elder mode, before pairing: scan the family's QR code or type the code. */
export default function Pair() {
  const { t } = useTranslation();
  const { scale } = useTheme();
  const params = useLocalSearchParams<{ code?: string }>();
  const chooseMode = useAppStore((state) => state.chooseMode);
  const [permission, requestPermission] = useCameraPermissions();
  const [scanning, setScanning] = useState(!params.code);
  const [code, setCode] = useState(params.code ?? '');
  const [notACode, setNotACode] = useState(false);
  const pairing = usePairing();
  const handled = useRef(false);

  const claim = (value: string) => {
    const parsed = codeFromScan(value);
    if (!parsed) {
      setNotACode(true);
      return;
    }
    setNotACode(false);
    pairing.mutate(parsed, { onError: () => (handled.current = false) });
  };

  return (
    <Screen>
      <Title>{t('elder.pair_title')}</Title>
      <Body>{t('elder.pair_intro')}</Body>
      {scanning ? (
        permission?.granted ? (
          <View style={{ height: 320, borderRadius: scale.radius, overflow: 'hidden' }}>
            <CameraView
              style={{ flex: 1 }}
              facing="back"
              barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
              onBarcodeScanned={({ data }) => {
                if (handled.current || pairing.isPending) {
                  return;
                }
                handled.current = true;
                claim(data);
              }}
            />
          </View>
        ) : (
          <>
            <Body muted>{t('elder.camera_why')}</Body>
            <Button label={t('elder.allow_camera')} onPress={() => void requestPermission()} />
          </>
        )
      ) : (
        <>
          <Field
            label={t('elder.code_label')}
            value={code}
            onChangeText={setCode}
            autoCapitalize="characters"
            autoCorrect={false}
            maxLength={12}
          />
          <Button label={t('elder.connect')} busy={pairing.isPending} onPress={() => claim(code)} />
        </>
      )}
      {notACode ? <ErrorNote error={t('elder.not_a_code')} /> : null}
      <ErrorNote error={pairing.error} />
      <Button
        variant="secondary"
        label={scanning ? t('elder.type') : t('elder.scan')}
        onPress={() => setScanning(!scanning)}
      />
      <Button variant="secondary" label={t('common.back')} onPress={() => void chooseMode(null)} />
    </Screen>
  );
}
