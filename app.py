from flask import Flask, escape, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import json
import googlemaps
import shortuuid
from flask_pymongo import PyMongo
import requests
import os
import config

app = Flask(__name__, static_folder='templates')
app.config["MONGO_URI"] = config.mongodburl
mongo = PyMongo(app)
CORS(app)

# Serve React App

@app.route('/post-location-inputs', methods=['POST'])
def postLocationInputs():
    data = request.get_json(silent=True)
    print(data)
    data = json.loads(data.get("data"))
    print(data)
    locations = data["locations"]
    category = data["category"]
    nearest_places = find_places(locations, category)
    print(locations)
    print(category)

    return jsonify(nearest_places)


@app.route('/generate-share-link', methods=['POST'])
def generate_share_link():
    data = request.get_json(silent=True)
    data = json.loads(data.get("data"))
    nearest_places = data["nearest_places"]

    id = shortuuid.uuid()
    mongo.db.data.insert({'uuid': id, 'nearest_places': nearest_places})
    share_url = id
    return share_url

@app.route('/get-share', methods=['POST'])
def load_share_link():
    data = request.get_json(silent=True)
    data = json.loads(data.get("data"))
    id = data["id"]

    row = mongo.db.data.find_one({'uuid': id})
    row.pop('_id', None)
    row.pop('uuid', None)

    output_json = json.dumps(row)
    return output_json

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')


# Google Maps Client and credentials
key = config.key
client = googlemaps.Client(key=key)

"""
Gets nearest restaurants as: [
	{
		"name": name
		"address": address
		"phone_number": phone_number
		"opening_hours": [
			"Monday: Closed",
			"Tuesday: 12:00 - 3:00 PM",
			etc.
		],
		"price_level": price_level (0-4, -1 if not included),
		"rating": rating (1.0-5.0, -1 if not included),
		"lat": lat
		"lng": lng
		"routes": [
			{
				origin: name
				origin_lat: lat
				origin_lng: lng
				html_instructions: ["turn right", "turn left", etc.]
			}
		]
		"photo_url": photo_url
	}
]
"""


def find_places(locations, query):
	"""
	Entry point for the module - you should only be using these functions
	:param locations: A LIST of strings, each representing the location of a user
	:param query: A STRING, representing what the user wants to do (restaurants, hotels etc.)
	:return:
	"""
	# Loops through the location names and obtains the XY coordinates of them
	coordinates = [get_xy(loc) for loc in locations]

	# Finds the central coordinates from the locations
	x, y = get_central_xy(coordinates)
	print("The central location is at Latitude {y}, Longitude {x}".format(x=x, y=y))

	print("Getting nearest places...")

	return get_nearest_places(locations=locations, coordinates=coordinates, lat=y, lng=x, query=query)


# IGNORE EVERYTHING BELOW HERE THAT IS NOT FOR YOU TIM


def get_xy(location):
	location_from_client = client.geocode(location)[0]["geometry"]["location"]
	lng, lat = location_from_client["lng"], location_from_client["lat"]

	return lng, lat


def get_central_xy(coordinates):
	length = len(coordinates)
	sum_x = sum([coord[0] for coord in coordinates])
	sum_y = sum([coord[1] for coord in coordinates])

	return sum_x / length, sum_y / length


def get_nearest_places(locations, coordinates, lat, lng, query):
	MAX_LENGTH = 3

	places = client.places(
		query=query,
		location=(lat, lng),
		radius="1500",
	)

	out = []

	for result in places["results"]:
		if len(out) >= MAX_LENGTH:
			break

		name = result["name"]
		address = result["formatted_address"]
		place_id = result["place_id"]
		lat = result["geometry"]["location"]["lat"]
		lng = result["geometry"]["location"]["lng"]

		photo_url, phone_number, opening_hours, maps_url, price_level, rating = get_place_details(place_id)

		out.append({
			"name": name,
			"address": address,
			"phone_number": phone_number,
			"opening_hours": opening_hours,
			"price_level": price_level,
			"rating": rating,
			"maps_url": maps_url,
			"lat": lat,
			"lng": lng,
			"routes": get_many_directions(locations, coordinates, lat, lng),
			"photo_url": photo_url,
		})

	return out


def get_place_details(place_id):
	place = client.place(
		place_id=place_id,
		fields=[
			"opening_hours",
			"website",
			"url",
			"formatted_phone_number",
			"url",
			"photo",
			"price_level",
			"rating"
		]
	)
	result = place["result"]

	# If statements to check that everything is there
	if "formatted_phone_number" in result:
		phone_number = result["formatted_phone_number"]
	else:
		phone_number = "None provided"
	if "opening_hours" in result:
		if "weekday_text" in result["opening_hours"]:
			opening_hours = result["opening_hours"]["weekday_text"]
		else:
			opening_hours = "None specified"
	else:
		opening_hours = ["None provided"]

	if "url" in result:
		maps_url = result["url"]
	else:
		maps_url = "None provided"

	if "photos" in result:
		photo_reference = result["photos"][0]["photo_reference"]
		photo_url = "https://maps.googleapis.com/maps/api/place/photo?maxwidth=1600&photoreference=" + photo_reference + "&key=" + key
		photo_url = requests.get(photo_url).url
	else:
		photo_url = "https://i.ytimg.com/vi/if-2M3K1tqk/maxresdefault.jpg"

	if "price_level" in result:
		price_level = str(result["price_level"])
	else:
		price_level = "-1"
	if "rating" in result:
		rating = str(result["rating"])
	else:
		rating = "-1"

	return photo_url, phone_number, opening_hours, maps_url, price_level, rating


def get_many_directions(starts, coordinates, dest_lat, dest_lng):
	route_infos = []

	for start, coord in zip(starts, coordinates):
		origin_lng, origin_lat = coord

		journey_length, html_instructions = get_directions(start, dest_lat, dest_lng)
		route_infos.append(
			{
				"origin": start,
				"origin_lat": str(origin_lat),
				"origin_lng": str(origin_lng),
				"journey_length": journey_length,
				"html_instructions": html_instructions,
			}
		)

	return route_infos


def get_directions(start, dest_lat, dest_lng):
	route_info = client.directions(start, str(dest_lat) + ", " + str(dest_lng))
	journey_length = ""
	html_instructions = []
	for path in route_info:
		for legs in path["legs"]:
			journey_length = legs["duration"]["text"]
			for steps in legs["steps"]:
				html_instructions.append(steps["html_instructions"])

	return journey_length, html_instructions


def get_photo(reference):
	MAX_WIDTH = 100
	return client.places_photo(reference, max_width=MAX_WIDTH)


if __name__ == "__main__":
	output = find_places(["London", "Oxford"], "Restaurants")
	for place in output:
		print("\nLocation: " + place["name"])
		print("Photo URL: " + place["photo_url"])
		print("Address: " + place["address"])
		print("Phone number: " + place["phone_number"])
		print("Google Maps URL: " + place["maps_url"])
		print("Opening Hours:")
		for text in place["opening_hours"]:
			print("\t" + text)
		print("Price Level: " + place["price_level"])
		print("Rating: " + place["rating"])
		for route in place["routes"]:
			print("\nThe journey will take {length} from {origin}".format(
				origin=route["origin"],
				length=route["journey_length"]))
			print("{} has latitude {} and longitude {}".format(
				route["origin"],
				route["origin_lat"],
				route["origin_lng"],
			))
