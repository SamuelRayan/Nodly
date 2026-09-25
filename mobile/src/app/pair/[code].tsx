import { Redirect, useLocalSearchParams } from 'expo-router';

/** nodly://pair/<code> (the pairing QR opened by the phone's camera app) fills in the code. */
export default function PairLink() {
  const { code } = useLocalSearchParams<{ code: string }>();
  return <Redirect href={{ pathname: '/pair', params: { code } }} />;
}
