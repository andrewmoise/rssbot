import argparse
import json

def read_banlist(filename):
    with open(filename, 'r') as file:
        return set(line.strip() for line in file)
    
def write_list_to_file(filename, user_list):
    with open(filename, 'w') as file:
        for user in user_list:
            file.write(f"{user}\n")

def main():
    parser = argparse.ArgumentParser(description="Compare two banlists and output the differences")
    parser.add_argument("list1", help="First banlist file")
    parser.add_argument("list2", help="Second banlist file")

    args = parser.parse_args()

    banlist1 = read_banlist(args.list1)
    banlist2 = read_banlist(args.list2)

    both_lists = sorted(banlist1 & banlist2)
    only_in_list1 = sorted(banlist1 - banlist2)
    only_in_list2 = sorted(banlist2 - banlist1)

    write_list_to_file("both_lists.txt", both_lists)
    write_list_to_file("only_in_list1.txt", only_in_list1)
    write_list_to_file("only_in_list2.txt", only_in_list2)

    print("Comparison complete. Results written to 'both_lists.txt', 'only_in_list1.txt', and 'only_in_list2.txt'.")

if __name__ == "__main__":
    main()
