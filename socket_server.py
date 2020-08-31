import socket, ssl, uuid
from threading import Thread 
import json
import jwt, hashlib
import time
from enum import Enum

from modbus_tk import modbus_tcp
import modbus_tk.defines as cst
import modbus_tk

# address enumerate
class AddrType(Enum):
    PI_IP_eth0 = "192.168.3.102"
    PI_IP_eht1 = "192.168.4.102"
    PI_PORT = 8001
    TBAS_IP_eth0 = "192.168.1.100"
    TBAS_IP_eth1 = "192.168.2.100"
    TBAS_PORT = 8001
    CP_IP_eth0 = "140.116.164.141"
    CP_IP_eth1 = "192.168.1.101"
    CP_PORT = 8001

# temporary database
class TempAccount(Enum):
    account = "a"
    passwd = "48c8947f69c054a5caa934674ce8881d02bb18fb59d5a63eeaddff735b0e9801e87294783281ae49fc8287a0fd86779b27d7972d3e84f0fa0d826d7cb67dfefc"
    key = "456"

# JWT from TBAS
jwtFromTBAS = b''

# thread class
class ServerThread(Thread):

    def __init__(self, conn, addr):
        Thread.__init__(self)
        self._conn = conn
        self._addr = addr
        
    def run(self):
        global jwtFromTBAS
        while True:
            dataFromTBASorCP = self._conn.recv(2048)
            print ("From", self._addr, ": " + dataFromTBASorCP.decode("utf-8"))
            
            # connect by TBAS
            if self._addr[0] == AddrType.TBAS_IP_eth1.value:
                jwtFromTBAS = dataFromTBASorCP
                self._conn.sendall("Pi got TBAS's Token.".encode("utf-8"))
                self._conn.close()
                print(self._addr, "disconnect!")
                break
            # connect by control program
            elif self._addr[0] == AddrType.CP_IP_eth1.value:
                # "JWT from TBAS" and "JWT from control program" are the same
                if jwtFromTBAS == dataFromTBASorCP:
                    try:
                        decodedData = jwt.decode(dataFromTBASorCP, jwt.decode(dataFromTBASorCP, verify=False)["public_key"].encode("utf-8")
                            , issuer=AddrType.TBAS_IP_eth0.value, audience=self._addr[0], algorithm='RS256')
                        print(decodedData)
                        self._conn.sendall("Legal".encode("utf-8"))

                        """ Pi send request to device for request data or control device,
                            Pi send data(with token) obtained from device to control program """
                        master = modbus_tcp.TcpMaster(decodedData.converter_ip, decodedData.converter_port)
                        try:
                            response = master.execute(slave=1, function_code=cst.READ_INPUT_REGISTERS, starting_address=0, quantity_of_x=3)
                            print(response)
                            # print("Humidity :", format(float(response[0])/float(100),'.2f'))
                            # print("Temperature (Celsius) :", format(float(response[1])/float(100),'.2f'))
                            # print("Temperature (Fahrenheit) :", format(float(response[2])/float(100),'.2f'))
                        except modbus_tk.modbus.ModbusError as exc:
                            print("%s- Code=%d", exc, exc.get_exception_code())
                            self._conn.close()
                            print(self._addr, "disconnect!")
                        except modbus_tcp.ModbusInvalidMbapError as exc:
                            print(exc)
                            self._conn.close()
                            print(self._addr, "disconnect!")

                        # time.sleep(12)
                        # self._conn.sendall(dataFromTBASorCP)

                        # # wait for feadback of control program
                        # dataFromCP = self._conn.recv(1024).decode("utf-8")

                        connectTBAS(response)
                        self._conn.sendall(jwtFromTBAS)
                        dataFromCP = self._conn.recv(1024).decode("utf-8")
                        
                        while True:
                            
                            # Token from Pi is legal
                            if dataFromCP == "close":
                                print("Token from Pi is legal.")
                                self._conn.close()
                                print(self._addr, "disconnect!")
                                break
                            # Token from Pi is illegal, resend verification information to TBAS
                            else:
                                print("Token from Pi is illegal.")
                                connectTBAS(response)
                                self._conn.sendall(jwtFromTBAS)
                                dataFromCP = self._conn.recv(1024).decode("utf-8")

                        
                    except jwt.InvalidSignatureError:
                        print("Signature verification failed.")
                        self._conn.sendall("Signature verification failed.".encode("utf-8"))
                    except jwt.DecodeError:
                        print("Decode Error.")
                        self._conn.sendall("Decode Error.".encode("utf-8"))
                    except jwt.ExpiredSignatureError:
                        print("Signature has expired.")
                        self._conn.sendall("Signature has expired.".encode("utf-8"))
                    except jwt.InvalidAudienceError:
                        print("Audience is error.")
                        self._conn.sendall("Audience is error.".encode("utf-8"))
                    except jwt.InvalidIssuerError:
                        print("Issue is error.")
                        self._conn.sendall("Issue is error.".encode("utf-8"))
                    except jwt.InvalidIssuedAtError:
                        print("The time of the Token was issued which is error.")
                        self._conn.sendall("The time of the Token was issued which is error.".encode("utf-8"))
                else:
                    self._conn.sendall("Your Token is illegal.".encode("utf-8"))

                break
            # if control program send "close", then close connection
            if dataFromTBASorCP.decode("utf-8") == "close":
                self._conn.close()
                print(self._addr, "disconnect!")
                break

# connect TBAS and send data to TBAS
def connectTBAS(response):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.load_verify_locations("./key/certificate.pem")
    context.options |= (ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_2)
    with context.wrap_socket(socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)) as sock:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.connect((AddrType.TBAS_IP_eth0.value, AddrType.TBAS_PORT.value))
            dic = {}
            # dic["account"] = input("Please enter your account : ")
            # dic["passwd"] = input("Please enter your password : ")
            # dic["account"] = "a"
            # dic["passwd"] = "123"
            dic["hostname"] = socket.gethostname()
            dic["mac_addr"] = uuid.UUID(int = uuid.getnode()).hex[-12:]
            dic["CP_ip"] = AddrType.CP_IP_eth1.value
            dic["CP_port"] = AddrType.CP_PORT.value
            dic["response"] = response

            sock.sendall(bytes(json.dumps(dic), encoding="utf-8"))
            dataFromTBAS = sock.recv(2048)
            global jwtFromTBAS
            jwtFromTBAS = dataFromTBAS

            sock.sendall("close".encode("utf-8"))

        except socket.error:
            print ("Connect error")

def main():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    # load private key and certificate file
    context.load_cert_chain("./key/certificate.pem", "./key/privkey.pem")
    # prohibit the use of TLSv1.0, TLgSv1.1, TLSv1.2 -> use TLSv1.3
    context.options |= (ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_2)

    # open, bind, listen socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0) as sock:
        sock.bind((AddrType.PI_IP_eth0.value, AddrType.PI_PORT.value))
        sock.listen(5)
        print ("Server start at: %s:%s" %(AddrType.PI_IP_eth0.value, AddrType.PI_PORT.value))
        print ("Wait for connection...")

        with context.wrap_socket(sock, server_side=True) as ssock:
            while True:
                try:
                    conn, addr = ssock.accept()
                    # multi-thread
                    newThread = ServerThread(conn, addr)
                    newThread.start()
                    newThread.join()
                    
                except KeyboardInterrupt:
                    break

if __name__ == "__main__":
    main()