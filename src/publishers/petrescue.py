#!/usr/bin/python

import configuration
import i18n
import medical
import sys
import utils

from base import AbstractPublisher
from sitedefs import SERVICE_URL, PETRESCUE_URL

class PetRescuePublisher(AbstractPublisher):
    """
    Handles publishing to petrescue.com.au
    """
    def __init__(self, dbo, publishCriteria):
        publishCriteria.uploadDirectly = True
        publishCriteria.thumbnails = False
        AbstractPublisher.__init__(self, dbo, publishCriteria)
        self.initLog("petrescue", "PetRescue Publisher")

    def get_breed_names(self, an):
        """
        Returns the comma separated list of breeds for the animal.
        """
        if an.CROSSBREED == 1:
            return "%s,%s" % (self.get_breed_name(an.SPECIESNAME, an.BREEDNAME1), self.get_breed_name(an.SPECIESNAME, an.BREEDNAME2))
        else:
            return self.get_breed_name(an.SPECIESNAME, an.BREEDNAME1)

    def get_breed_name(self, sname, bname):
        """
        Ensures that if sname == "Cat" or "Dog" that the bname is one from our
        list 
        """
        maps = {
            "Cat":  ( "Domestic Short Hair", CAT_BREEDS ),
            "Dog":  ( "Mixed Breed", DOG_BREEDS ),
            "Horse": ( "Horse", HORSE_BREEDS ),
            "Rabbit": ( "Bunny", RABBIT_BREEDS )
        }
        if sname not in maps: 
            self.log("No mappings for species '%s'" % sname)
            return bname
        default_breed, breed_list = maps[sname]
        for d in breed_list:
            if d["name"] == bname:
                return bname
        self.log("'%s' is not a valid PetRescue breed, using default '%s'" % (bname, default_breed))
        return default_breed

    def run(self):
        
        self.log("PetRescuePublisher starting...")

        if self.isPublisherExecuting(): return
        self.updatePublisherProgress(0)
        self.setLastError("")
        self.setStartPublishing()

        token = configuration.petrescue_token(self.dbo)
        postcode = configuration.organisation_postcode(self.dbo)
        contact_name = configuration.organisation(self.dbo)
        contact_email = configuration.email(self.dbo)
        contact_number = configuration.organisation_telephone(self.dbo)

        if token == "":
            self.setLastError("No PetRescue auth token has been set.")
            return

        if postcode == "" or contact_email == "":
            self.setLastError("You need to set your organisation postcode and contact email under Settings->Options->Shelter Details->Email")
            return

        animals = self.getMatchingAnimals()
        processed = []

        if len(animals) == 0:
            self.setLastError("No animals found to publish.")
            self.cleanup()
            return

        headers = { "Authorization": "Token token=%s" % token, "Accept": "*/*" }

        anCount = 0
        for an in animals:
            try:
                anCount += 1
                self.log("Processing: %s: %s (%d of %d)" % ( an["SHELTERCODE"], an["ANIMALNAME"], anCount, len(animals)))
                self.updatePublisherProgress(self.getProgress(anCount, len(animals)))

                # If the user cancelled, stop now
                if self.shouldStopPublishing(): 
                    self.log("User cancelled publish. Stopping.")
                    self.resetPublisherProgress()
                    self.cleanup()
                    return
       
                isdog = an.SPECIESID == 1
                iscat = an.SPECIESID == 2

                ageinyears = i18n.date_diff_days(an.DATEOFBIRTH, i18n.now())

                vaccinated = medical.get_vaccinated(self.dbo, an.ID)
                
                size = ""
                if an.SIZE == 2: size = "medium"
                elif an.SIZE < 2: size = "large"
                else: size = "small"

                coat = ""
                if an.COATTYPE == 0: coat = "short"
                elif an.COATTYPE == 1: coat = "long"
                else: coat = "medium_coat"

                origin = ""
                if an.ISTRANSFER == 1 and str(an.BROUGHTINBYOWNERNAME).lower().find("pound") == -1: origin = "shelter_transfer"
                elif an.ISTRANSFER == 1 and str(an.BROUGHTINBYOWNERNAME).lower().find("pound") != -1: origin = "pound_transfer"
                elif an.ORIGINALOWNERID > 0: origin = "owner_surrender"
                else: origin = "community_cat"

                photo_url = "%s?account=%s&method=animal_image&animalid=%d" % (SERVICE_URL, self.dbo.database, an.ID)

                # Construct a dictionary of info for this animal
                data = {
                    "remote_id":                str(an.ID), # animal identifier in ASM
                    "remote_source":            "SM%s" % self.dbo.database, # system/database identifier
                    "name":                     an.ANIMALNAME.title(), # animal name (title case, they validate against caps)
                    "adoption_fee":             i18n.format_currency_no_symbol(self.locale, an.FEE),
                    "species_name":             an.SPECIESNAME,
                    "breed_names":              self.get_breed_names(an), # breed1,breed2 or breed1
                    "mix":                      an.CROSSBREED == 1, # true | false
                    "date_of_birth":            i18n.format_date("%Y-%m-%d", an.DATEOFBIRTH), # iso
                    "gender":                   an.SEXNAME.lower(), # male | female
                    "personality":              an.WEBSITEMEDIANOTES, # 20-4000 chars of free type
                    "location_postcode":        postcode, # shelter postcode
                    "postcode":                 postcode, # shelter postcode
                    "microchip_number":         utils.iif(an.IDENTICHIPPED == 1, an.IDENTICHIPNUMBER, ""), 
                    "desexed":                  an.NEUTERED == 1,# true | false, validates to always true according to docs
                    "contact_method":           "email", # email | phone
                    "size":                     utils.iif(isdog, size, ""), # dogs only - small | medium | high
                    "senior":                   isdog and ageinyears > 7, # dogs only, true | false
                    "vaccinated":               vaccinated, # cats, dogs, rabbits, true | false
                    "wormed":                   vaccinated, # cats & dogs, true | false
                    "heart_worm_treated":       vaccinated, # dogs only, true | false
                    "coat":                     utils.iif(iscat, coat, ""), # cats only, short | medium_coat | long
                    "intake_origin":            utils.iif(iscat, origin, ""), # cats only, community_cat | owner_surrender | pound_transfer | shelter_transfer
                    "adoption_process":         "", # 4,000 chars how to adopt
                    "contact_details_source":   "self", # self | user | group
                    "contact_preferred_method": "email", # email | phone
                    "contact_name":             contact_name, # name of contact details owner
                    "contact_number":           contact_number, # number to enquire about adoption
                    "contact_email":            contact_email, # email to enquire about adoption
                    "foster_needed":            False, # true | false
                    "interstate":               True, # true | false - can the animal be adopted to another state
                    "medical_notes":            an.HEALTHPROBLEMS, # 4,000 characters medical notes
                    "multiple_animals":         False, # More than one animal included in listing true | false
                    "photo_urls":               [ photo_url ], # List of photo URL strings
                    "status":                   "active" # active | removed | on_hold | rehomed | suspended | group_suspended
                }

                # PetRescue will insert/update accordingly based on whether remote_id/remote_source exists
                url = PETRESCUE_URL + "listings"
                jsondata = utils.json(data)
                self.log("Sending POST to %s to create/update listing: %s" % (url, jsondata))
                r = utils.post_json(url, jsondata, headers=headers)

                if r["status"] != 200:
                    self.logError("HTTP %d, headers: %s, response: %s" % (r["status"], r["headers"], r["response"]))
                else:
                    self.log("HTTP %d, headers: %s, response: %s" % (r["status"], r["headers"], r["response"]))
                    self.logSuccess("Processed: %s: %s (%d of %d)" % ( an["SHELTERCODE"], an["ANIMALNAME"], anCount, len(animals)))
                    processed.append(an)

            except Exception as err:
                self.logError("Failed processing animal: %s, %s" % (str(an["SHELTERCODE"]), err), sys.exc_info())

        # Next, identify animals we've previously sent who:
        # 1. Have an active exit movement in the last month or died in the last month
        # 2. Have an entry in animalpublished/petrescue where the sent date is older than the active movement
        # 3. Have an entry in animalpublished/petrescue where the sent date is older than the deceased date

        animals = self.dbo.query("SELECT a.ID, a.ShelterCode, a.AnimalName, p.SentDate, a.ActiveMovementDate, a.DeceasedDate FROM animal a " \
            "INNER JOIN animalpublished p ON p.AnimalID = a.ID AND p.PublishedTo='petrescue' " \
            "WHERE Archived = 1 AND ((DeceasedDate Is Not Null AND DeceasedDate >= ?) OR " \
            "(ActiveMovementDate Is Not Null AND ActiveMovementDate >= ? AND ActiveMovementType NOT IN (2,8))) " \
            "ORDER BY a.ID", [self.dbo.today(offset=-30), self.dbo.today(offset=-30)])

        for an in animals:
            if (an.ACTIVEMOVEMENTDATE and an.SENTDATE < an.ACTIVEMOVEMENTDATE) or (an.DECEASEDDATE and an.SENTDATE < an.DECEASEDDATE):
                
                status = utils.iif(an.DECEASEDDATE is not None, "removed", "rehomed")
                data = { "status": status }
                jsondata = utils.json(data)
                url = PETRESCUE_URL + "listings/%s/SM%s" % (an.ID, self.dbo.database)

                self.log("Sending PATCH to %s to update existing listing: %s" % (url, jsondata))
                r = utils.patch_json(url, jsondata, headers=headers)

                if r["status"] != 200:
                    self.logError("HTTP %d, headers: %s, response: %s" % (r["status"], r["headers"], r["response"]))
                else:
                    self.log("HTTP %d, headers: %s, response: %s" % (r["status"], r["headers"], r["response"]))
                    self.logSuccess("%s - %s: Marked with new status %s" % (an.SHELTERCODE, an.ANIMALNAME, status))
                    # By marking these animals in the processed list again, their SentDate
                    # will become today, which should exclude them from sending these status
                    # updates to close the listing again in future
                    processed.append(an)

        # Mark sent animals published
        self.markAnimalsPublished(processed, first=True)

        self.cleanup()



# These breed lists were retrieved by doing:
# curl -H "Content-Type: application/json"  "https://special.petrescue.com.au/api/v2/breeds?species_name=X&token=Y" > cats.json

# We use a directive to prevent flake8 choking on the long lines - # noqa: E501

DOG_BREEDS = [{"id":1,"name":"Affenpinscher"},{"id":2,"name":"Afghan Hound"},{"id":3,"name":"Airedale"},{"id":4,"name":"Akita Inu"},{"id":5,"name":"Alaskan Malamute"},{"id":6,"name":"Alsatian"},{"id":7,"name":"American Bulldog"},{"id":8,"name":"American Eskimo Dog"},{"id":9,"name":"American Staffordshire Terrier"},{"id":10,"name":"American Water Spaniel"},{"id":11,"name":"Amstaff"},{"id":12,"name":"Anatolian Shepherd"},{"id":13,"name":"Appenzell Mountain Dog"},{"id":14,"name":"Australian Bulldog"},{"id":15,"name":"Australian Cattle Dog"},{"id":16,"name":"Australian Shepherd"},{"id":17,"name":"Australian Stumpy Tail Cattle Dog"},{"id":18,"name":"Australian terrier"},{"id":19,"name":"Azawakh (Tuareg Sloughi)"},{"id":20,"name":"Basenji"},{"id":21,"name":"Basset Fauve De Bretagne"},{"id":22,"name":"Basset Hound"},{"id":23,"name":"Beagle"},{"id":24,"name":"Bearded Collie"},{"id":25,"name":"Bedlington Terrier"},{"id":26,"name":"Belgian Shepherd - Groenendael"},{"id":27,"name":"Belgian Shepherd - Laekenois"},{"id":28,"name":"Belgian Shepherd - Malinois"},{"id":29,"name":"Belgian Shepherd - Tervueren"},{"id":30,"name":"Belgium Griffon"},{"id":31,"name":"Bergamasco Shepherd Dog"},{"id":32,"name":"Bernese Mountain Dog"},{"id":33,"name":"Bichon Frise"},{"id":34,"name":"Black Russian Terrier"},{"id":35,"name":"Bloodhound"},{"id":36,"name":"Blue Heeler"},{"id":37,"name":"Border Collie"},{"id":38,"name":"Border Terrier"},{"id":39,"name":"Borzoi (Russian Wolfhound)"},{"id":40,"name":"Boston Terrier"},{"id":41,"name":"Bouvier Des Flandres"},{"id":42,"name":"Boxer"},{"id":43,"name":"Bracco Italiano"},{"id":44,"name":"Briard"},{"id":45,"name":"British Bulldog"},{"id":46,"name":"Brittany Spaniel"},{"id":47,"name":"Brussels Griffon"},{"id":48,"name":"Bull Arab"},{"id":49,"name":"Bull Terrier"},{"id":50,"name":"Bullmastiff"},{"id":51,"name":"Cairn Terrier"},{"id":52,"name":"Canaan Dog (Kelev K'naani)"},{"id":53,"name":"Canadian Eskimo Dog"},{"id":54,"name":"Catahoula"},{"id":55,"name":"Cavalier King Charles Spaniel"},{"id":56,"name":"Central Asian Shepherd Dog"},{"id":57,"name":"Cesky Terrier"},{"id":58,"name":"Chesapeake Bay Retriever"},{"id":59,"name":"Chihuahua"},{"id":60,"name":"Chinese Crested"},{"id":61,"name":"Chow Chow"},{"id":62,"name":"Clumber Spaniel"},{"id":63,"name":"Cocker Spaniel, American"},{"id":64,"name":"Cocker Spaniel, English"},{"id":65,"name":"Collie Rough"},{"id":66,"name":"Collie Smooth"},{"id":67,"name":"Coonhound"},{"id":68,"name":"Corgi, Cardigan"},{"id":69,"name":"Corgi, Pembroke"},{"id":70,"name":"Cross breed"},{"id":71,"name":"Curly Coated Retriever"},{"id":72,"name":"Dachshund"},{"id":73,"name":"Dalmatian"},{"id":74,"name":"Dandie Dinmont Terrier"},{"id":75,"name":"Deer Hound"},{"id":76,"name":"Dingo"},{"id":77,"name":"Doberman"},{"id":78,"name":"Dogue De Bordeaux"},{"id":79,"name":"Dutch Shepherd"},{"id":80,"name":"English Setter"},{"id":81,"name":"English Springer Spaniel"},{"id":82,"name":"Eurasier"},{"id":83,"name":"Field Spaniel"},{"id":84,"name":"Finnish Lapphund"},{"id":85,"name":"Finnish Spitz"},{"id":86,"name":"Flat Coated Retriever"},{"id":87,"name":"Fox Terrier"},{"id":88,"name":"Foxhound, American"},{"id":89,"name":"Foxhound, English"},{"id":90,"name":"French Bulldog"},{"id":91,"name":"German Hunting Terrier"},{"id":92,"name":"German Pinscher"},{"id":93,"name":"German Shepherd"},{"id":94,"name":"German Shorthaired Pointer"},{"id":95,"name":"German Spitz"},{"id":96,"name":"German Wirehaired Pointer"},{"id":97,"name":"Glen of Imaal Terrier"},{"id":98,"name":"Golden Retriever"},{"id":99,"name":"Gordon Setter"},{"id":100,"name":"Great Dane"},{"id":101,"name":"Greyhound"},{"id":102,"name":"Griffon"},{"id":103,"name":"Hamiltonstovare"},{"id":104,"name":"Harrier"},{"id":105,"name":"Havanese"},{"id":106,"name":"Hungarian Puli"},{"id":107,"name":"Hungarian Vizsla"},{"id":108,"name":"Huntaway"},{"id":109,"name":"Husky"},{"id":110,"name":"Ibizan Hound"},{"id":111,"name":"Irish Setter"},{"id":112,"name":"Irish Terrier"},{"id":113,"name":"Irish Water Spaniel"},{"id":114,"name":"Irish Wolfhound"},{"id":115,"name":"Italian Corso Dog"},{"id":116,"name":"Italian Greyhound"},{"id":117,"name":"Italian Spinone"},{"id":118,"name":"Jack Russell Terrier"},{"id":119,"name":"Japanese Chin"},{"id":120,"name":"Japanese Tosa"},{"id":121,"name":"Johnson Bulldog"},{"id":122,"name":"Kangal Dog"},{"id":123,"name":"Keeshond"},{"id":124,"name":"Kelpie"},{"id":125,"name":"Kerry Blue Terrier"},{"id":126,"name":"King Charles Spaniel"},{"id":127,"name":"Komondor (Hungarian Sheepdog)"},{"id":128,"name":"Koolie"},{"id":129,"name":"Kuvasz"},{"id":130,"name":"Labradoodle"},{"id":131,"name":"Labrador"},{"id":132,"name":"Lagotto Romagnolo"},{"id":133,"name":"Lakeland Terrier"},{"id":134,"name":"Large Munsterlander"},{"id":135,"name":"Leonberger"},{"id":136,"name":"Lhasa Apso"},{"id":137,"name":"Lowchen"},{"id":138,"name":"Maltese"},{"id":139,"name":"Manchester Terrier"},{"id":140,"name":"Maremma Sheepdog"},{"id":141,"name":"Mastiff"},{"id":142,"name":"Min Pin"},{"id":143,"name":"Mini Pinscher"},{"id":144,"name":"Miniature Fox Terrier"},{"id":146,"name":"Neapolitan Mastiff"},{"id":147,"name":"Newfoundland"},{"id":148,"name":"Norfolk Terrier"},{"id":149,"name":"Norwegian Buhund"},{"id":150,"name":"Norwegian Elkhound"},{"id":151,"name":"Norwich Terrier"},{"id":152,"name":"Nova Scotia Duck Tolling Retriever"},{"id":153,"name":"Old English Sheepdog"},{"id":154,"name":"Otterhound"},{"id":155,"name":"Papillion"},{"id":156,"name":"Parsons Jack Russell Terrier"},{"id":157,"name":"Patterdale Terrier"},{"id":158,"name":"Pekingese"},{"id":159,"name":"Peruvian Hairless Dog"},{"id":160,"name":"Petit Basset Griffon Vendeen"},{"id":161,"name":"Pharoah Hound"},{"id":163,"name":"Pointer"},{"id":164,"name":"Polish Lowland Sheepdog"},{"id":165,"name":"Pomeranian"},{"id":166,"name":"Poodle"},{"id":167,"name":"Portuguese Podengo"},{"id":168,"name":"Portuguese Water Dog"},{"id":169,"name":"Pug"},{"id":170,"name":"Pumi"},{"id":171,"name":"Pyrenean Mastiff"},{"id":172,"name":"Pyrenean Mountain Dog"},{"id":173,"name":"Rat Terrier"},{"id":174,"name":"Red Heeler"},{"id":175,"name":"Red Setter"},{"id":176,"name":"Rhodesian Ridgeback"},{"id":177,"name":"Rottweiler"},{"id":178,"name":"Saint Bernard"},{"id":179,"name":"Saluki"},{"id":180,"name":"Samoyed"},{"id":181,"name":"Schipperke"},{"id":182,"name":"Schnauzer, Giant"},{"id":183,"name":"Schnauzer, Miniature"},{"id":184,"name":"Schnauzer, Standard"},{"id":185,"name":"Scottish Terrier"},{"id":186,"name":"Sealyham Terrier"},{"id":187,"name":"Shar-Pei"},{"id":188,"name":"Shetland Sheepdog"},{"id":189,"name":"Shiba Inu"},{"id":190,"name":"Shih Tzu"},{"id":191,"name":"Siberian Husky"},{"id":192,"name":"Silky Terrier"},{"id":193,"name":"Skye Terrier"},{"id":194,"name":"Sloughi"},{"id":195,"name":"Smithfield Cattle Dog"},{"id":196,"name":"Spanish Mastiff"},{"id":197,"name":"Spitz"},{"id":198,"name":"Staffordshire Bull Terrier"},{"id":199,"name":"Staffy"},{"id":200,"name":"Staghound"},{"id":201,"name":"Sussex Spaniel"},{"id":202,"name":"Swedish Lapphund"},{"id":203,"name":"Swedish Vallhund"},{"id":204,"name":"Swiss Mountain Dog"},{"id":205,"name":"Tenterfield Terrier"},{"id":206,"name":"Tibetan Mastiff"},{"id":207,"name":"Tibetan Spaniel"},{"id":208,"name":"Tibetan Terrier"},{"id":209,"name":"Timber Shepherd"},{"id":210,"name":"Weimaraner"},{"id":211,"name":"Welsh Springer Spaniel"},{"id":212,"name":"Welsh Terrier"},{"id":213,"name":"West Highland White Terrier"},{"id":214,"name":"Wheaten Terrier"},{"id":215,"name":"Whippet"},{"id":216,"name":"White Shepherd Dog"},{"id":217,"name":"Yorkshire Terrier"},{"id":344,"name":"Terrier"},{"id":352,"name":"Wolfhound"},{"id":382,"name":"Ridgeback"},{"id":443,"name":"Sheltie"},{"id":460,"name":"English"},{"id":473,"name":"Mixed"},{"id":591,"name":"Papillon"},{"id":1414,"name":"Welsh Corgi"},{"id":2118,"name":"Tan"},{"id":2508,"name":"Hairless"},{"id":2625,"name":"American"},{"id":3991,"name":"Bull Terrier (Miniature)"},{"id":4006,"name":"Crested"},{"id":4266,"name":"Fox"},{"id":4534,"name":"Silver"},{"id":6748,"name":"Harlequin"},{"id":6781,"name":"Rex"},{"id":7843,"name":"Turkish Kangal"},{"id":8265,"name":"Mixed Breed"},{"id":8505,"name":"American Staffordshire Bull Terrier"},{"id":124069,"name":"Prague Ratter"},{"id":165093,"name":"Sarplaninac"},{"id":180330,"name":"English Toy Terrier"}] # noqa: E501


CAT_BREEDS = [{"id":218,"name":"Abyssinian"},{"id":219,"name":"American Curl"},{"id":220,"name":"American Shorthair"},{"id":221,"name":"Angora"},{"id":222,"name":"Asian"},{"id":223,"name":"Australian Mist"},{"id":224,"name":"Balinese"},{"id":225,"name":"Bengal"},{"id":226,"name":"Birman"},{"id":227,"name":"Bombay"},{"id":228,"name":"British Blue"},{"id":229,"name":"British Longhair"},{"id":230,"name":"British Shorthair"},{"id":231,"name":"Burmese"},{"id":232,"name":"Burmilla"},{"id":233,"name":"Chartreux"},{"id":234,"name":"Chinchilla"},{"id":235,"name":"Cornish Rex"},{"id":236,"name":"Cymric"},{"id":237,"name":"Devon Rex"},{"id":238,"name":"Domestic Long Hair"},{"id":240,"name":"Domestic Short Hair"},{"id":241,"name":"Egyptian Mau"},{"id":242,"name":"European Shorthair"},{"id":243,"name":"Exotic Shorthair"},{"id":244,"name":"Foreign White"},{"id":245,"name":"German Rex"},{"id":246,"name":"Havana"},{"id":247,"name":"Himalayan"},{"id":248,"name":"Japanese Bobtail"},{"id":249,"name":"Javanese"},{"id":250,"name":"Korat (Si-Sawat)"},{"id":251,"name":"LaPerm"},{"id":252,"name":"Layanese"},{"id":253,"name":"Maine Coon"},{"id":254,"name":"Manx"},{"id":255,"name":"Moggie"},{"id":256,"name":"Munchkin"},{"id":257,"name":"Nebelung"},{"id":258,"name":"Norwegian Forest Cat"},{"id":259,"name":"Ocicat"},{"id":260,"name":"Oriental"},{"id":261,"name":"Persian"},{"id":262,"name":"Polydactyl Cat"},{"id":263,"name":"Ragdoll"},{"id":264,"name":"Russian Blue"},{"id":265,"name":"Savannah Cat"},{"id":266,"name":"Scottish Fold"},{"id":267,"name":"Scottish Shorthair"},{"id":268,"name":"Selkirk Rex"},{"id":269,"name":"Siamese"},{"id":270,"name":"Siberian Cat"},{"id":271,"name":"Singapura"},{"id":272,"name":"Snowshoe"},{"id":273,"name":"Somali"},{"id":274,"name":"Sphynx"},{"id":275,"name":"Tonkinese"},{"id":276,"name":"Toyger"},{"id":277,"name":"Turkish Van"},{"id":4506,"name":"Lilac"},{"id":8247,"name":"Domestic Medium Hair"},{"id":8431,"name":"Ragamuffin"},{"id":22453,"name":"Australian Tiffanie"}] # noqa: E501

RABBIT_BREEDS = [{"id":295,"name":"American"},{"id":296,"name":"American Fuzzy Lop"},{"id":297,"name":"American Sable"},{"id":298,"name":"Angora"},{"id":299,"name":"Belgian Hare"},{"id":300,"name":"Beveren"},{"id":301,"name":"Britannia Petit"},{"id":302,"name":"British Giant"},{"id":303,"name":"Bunny"},{"id":304,"name":"Californian"},{"id":305,"name":"Californian Dwarf"},{"id":306,"name":"Cashmere"},{"id":307,"name":"Champagne D'argent"},{"id":308,"name":"Checkered Giant"},{"id":309,"name":"Cinnamon"},{"id":310,"name":"Dutch"},{"id":311,"name":"Dwarf"},{"id":312,"name":"Dwarf lop"},{"id":313,"name":"English"},{"id":314,"name":"English Lop"},{"id":315,"name":"English Spot"},{"id":316,"name":"Flemish Giant"},{"id":317,"name":"Florida White"},{"id":318,"name":"Fox"},{"id":319,"name":"French Angora"},{"id":320,"name":"French Lop"},{"id":321,"name":"Harlequin"},{"id":322,"name":"Havana"},{"id":323,"name":"Himalayan Dwarf"},{"id":324,"name":"Holland Lop"},{"id":325,"name":"Hotot"},{"id":326,"name":"Jersey Wooly"},{"id":327,"name":"Lilac"},{"id":328,"name":"Lop Eared"},{"id":329,"name":"Mini Lop"},{"id":330,"name":"Mini Rex"},{"id":331,"name":"Netherland Dwarf"},{"id":332,"name":"New Zealand White"},{"id":333,"name":"Palomino"},{"id":334,"name":"Papillon"},{"id":335,"name":"Polish"},{"id":336,"name":"Polish Dwarf"},{"id":337,"name":"Rex"},{"id":338,"name":"Rhinelander"},{"id":339,"name":"Satin"},{"id":340,"name":"Silver"},{"id":341,"name":"Silver Fox"},{"id":342,"name":"Silver Marten"},{"id":343,"name":"Tan"},{"id":8670,"name":"Domestic"},{"id":29250,"name":"Dutch giants"}] # noqa: E501

HORSE_BREEDS = [{"id":93986,"name":"Andalusian"},{"id":93987,"name":"Appaloosa"},{"id":93988,"name":"Arab"},{"id":93989,"name":"Australian Miniture Horse"},{"id":93990,"name":"Australian Pony Studbook"},{"id":93991,"name":"Australian Stock Horse"},{"id":93992,"name":"Brumby"},{"id":93993,"name":"Cleveland Bay Horse"},{"id":93994,"name":"Clydesdale"},{"id":93995,"name":"Connemara"},{"id":93996,"name":"Dartmoor Pony"},{"id":93997,"name":"Donkey"},{"id":93998,"name":"Draught"},{"id":93999,"name":"Fjord"},{"id":94000,"name":"Friesian"},{"id":94001,"name":"Gaited"},{"id":94002,"name":"Grade"},{"id":94003,"name":"Hackney"},{"id":94004,"name":"Haflinger"},{"id":94005,"name":"Hanovarian"},{"id":94006,"name":"Highland Pony"},{"id":94007,"name":"Holsteiner"},{"id":94008,"name":"Horse"},{"id":94009,"name":"Irish Draught Horse"},{"id":94010,"name":"Lippizaner"},{"id":94011,"name":"Missouri Foxtrotter"},{"id":94012,"name":"Morgan"},{"id":94013,"name":"Mustang"},{"id":94014,"name":"New Forest Pony"},{"id":94015,"name":"Paint/Pinto"},{"id":94016,"name":"Palamino"},{"id":94017,"name":"Paso Fino"},{"id":94018,"name":"Percheron"},{"id":94019,"name":"Peruvian Paso"},{"id":94020,"name":"Pony"},{"id":94021,"name":"Quarter Horse"},{"id":94022,"name":"Saddlebred"},{"id":94023,"name":"Shetland Pony"},{"id":94024,"name":"Shire"},{"id":94025,"name":"Standardbred"},{"id":94026,"name":"Tennessee Walker"},{"id":94027,"name":"Thoroughbred"},{"id":94028,"name":"Trakehner"},{"id":94029,"name":"Waler"},{"id":94030,"name":"Warmblood"},{"id":94031,"name":"Welsh Mountain Pony"}] # noqa: E501

