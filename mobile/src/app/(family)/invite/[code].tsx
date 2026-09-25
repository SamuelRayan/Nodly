import { Redirect, useLocalSearchParams } from 'expo-router';

/** nodly://invite/<code> (invite links and QR codes) opens the join screen with the code. */
export default function InviteLink() {
  const { code } = useLocalSearchParams<{ code: string }>();
  return <Redirect href={{ pathname: '/join', params: { code } }} />;
}
