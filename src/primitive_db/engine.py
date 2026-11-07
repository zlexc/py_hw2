import prompt


def print_help():
    print("<command> exit - выйти из программы")
    print("<command> help - справочная информация")


def welcome():
    print("Первая попытка запустить проект!")
    print("\n***")
    print_help()

    while True:
        try:
            command = prompt.string("Введите команду: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if command == "exit":
            break
        if command == "help":
            print_help()
        elif command:
            print("Неизвестная команда. Введите help для справки.")
